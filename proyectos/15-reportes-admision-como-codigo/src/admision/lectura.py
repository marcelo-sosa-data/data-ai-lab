"""
Lectura de los exports de cada campaña.

Cada archivo se lee por nombre de columna (con sinónimos), no por posición, y
lo que no cuadra con el contrato queda como hallazgo en vez de romper en
silencio: columnas que faltan o sobran, fechas que no se pueden leer o que
vienen con el mes primero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import catalogos as K
from . import normalizar as N


@dataclass
class Lectura:
    inscripciones: pd.DataFrame
    interesados: pd.DataFrame
    pagos: pd.DataFrame
    vacantes: pd.DataFrame
    hallazgos: list[dict] = field(default_factory=list)


def _hallazgo(lista, archivo: Path, campania: str, regla: str, severidad: str, detalle: str) -> None:
    lista.append({"campania": campania, "archivo": archivo.name, "regla": regla,
                  "severidad": severidad, "detalle": detalle})


def _leer_csv(ruta: Path) -> pd.DataFrame:
    crudo = ruta.read_bytes()
    try:
        texto = crudo.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        texto, encoding = crudo.decode("cp1252"), "cp1252"
    primera = texto.splitlines()[0] if texto else ""
    sep = ";" if primera.count(";") > primera.count(",") else ","
    return pd.read_csv(ruta, sep=sep, encoding=encoding, dtype=str, keep_default_na=False)


def _estandarizar(df: pd.DataFrame, tipo: str, ruta: Path, campania: str, hallazgos: list) -> pd.DataFrame | None:
    """Renombra a las columnas estándar. Devuelve None si falta una obligatoria."""
    sinonimos = K.SINONIMOS[tipo]
    inverso = {s: estandar for estandar, lista in sinonimos.items() for s in lista}
    nuevos, desconocidas = {}, []
    for col in df.columns:
        norm = N.encabezado(col)
        if norm in inverso and inverso[norm] not in nuevos.values():
            nuevos[col] = inverso[norm]
        else:
            desconocidas.append(str(col))
    faltan = [c for c in sinonimos if c not in nuevos.values() and c not in K.OPCIONALES[tipo]]
    if desconocidas:
        _hallazgo(hallazgos, ruta, campania, "columna_no_esperada", "aviso",
                  "columnas que no están en el contrato: " + ", ".join(desconocidas))
    if faltan:
        _hallazgo(hallazgos, ruta, campania, "columna_faltante", "error",
                  "faltan columnas obligatorias: " + ", ".join(faltan))
        return None
    df = df.rename(columns=nuevos)[list(nuevos.values())]
    for c in sinonimos:
        if c not in df.columns:
            df[c] = None
    return df[list(sinonimos)]


def _fechas(df, columnas, ruta, campania, hallazgos):
    for col in columnas:
        df[col], problema = N.fechas(df[col])
        if problema:
            regla = "fecha_mes_dia" if "mes/día" in problema else "fecha_ilegible"
            _hallazgo(hallazgos, ruta, campania, regla, "error", f"{col}: {problema}")


def leer_inscripciones(ruta: Path, campania: str, hallazgos: list) -> pd.DataFrame | None:
    df = _estandarizar(_leer_csv(ruta), "inscripciones", ruta, campania, hallazgos)
    if df is None:
        return None
    df["fila_archivo"] = range(2, len(df) + 2)
    df["codigo_postulante"] = df["codigo_postulante"].astype("string").str.strip()
    df["tipo_documento"] = df["tipo_documento"].map(N.clave)
    df["documento"] = [N.documento(d, t) for d, t in zip(df["documento"], df["tipo_documento"])]
    df["nombre_completo"] = df["nombre_completo"].map(N.clave)
    df["celular"] = df["celular"].map(N.celular)
    df["modalidad"] = N.mapear_catalogo(df["modalidad"], K.MODALIDADES)
    df["carrera"] = N.mapear_catalogo(df["carrera"], K.CARRERAS)
    df["sede"] = N.mapear_catalogo(df["sede"], K.SEDES)
    df["estado"] = df["estado"].map(lambda v: K.ESTADOS.get(N.clave(v), N.clave(v) or None))
    df["puntaje"] = pd.to_numeric(df["puntaje"].astype("string").str.replace(",", ".", regex=False)
                                  .replace("", pd.NA), errors="coerce")
    _fechas(df, ["fecha_inscripcion", "fecha_resultado", "fecha_actualizacion"], ruta, campania, hallazgos)
    df["es_prueba"] = df["documento"].isin(K.DOCUMENTOS_PRUEBA) | df["nombre_completo"].str.contains(
        r"\bPRUEBA\b", regex=True, na=False)
    df["campania"] = campania
    return df


def leer_interesados(ruta: Path, campania: str, hallazgos: list) -> pd.DataFrame | None:
    df = _estandarizar(pd.read_excel(ruta, dtype=object), "interesados", ruta, campania, hallazgos)
    if df is None:
        return None
    df["id_lead"] = df["id_lead"].astype("string").str.strip()
    df["nombre"] = df["nombre"].map(N.clave)
    df["documento"] = df["documento"].map(N.documento)
    df["celular"] = df["celular"].map(N.celular)
    df["canal"] = N.mapear_catalogo(df["canal"], K.CANALES)
    df["carrera"] = N.mapear_catalogo(df["carrera"], K.CARRERAS)
    df["sede"] = N.mapear_catalogo(df["sede"], K.SEDES)
    _fechas(df, ["fecha_registro"], ruta, campania, hallazgos)
    df["campania"] = campania
    return df


def leer_pagos(ruta: Path, campania: str, hallazgos: list) -> pd.DataFrame | None:
    df = _estandarizar(pd.read_excel(ruta, dtype=object), "pagos", ruta, campania, hallazgos)
    if df is None:
        return None
    df["documento_pagador"] = df["documento_pagador"].map(N.documento)
    df["doc_sin_ceros"] = df["documento_pagador"].map(N.documento_sin_ceros)
    df["concepto"] = df["concepto"].map(N.clave)
    df["tipo_pago"] = df["concepto"].map(
        lambda c: "MATRICULA" if c.startswith("MATRICULA") else ("DERECHO" if c.startswith("DERECHO") else "OTRO"))
    df["referencia_codigo"] = df["referencia"].map(N.referencia_codigo)
    df["monto"] = pd.to_numeric(df["monto"], errors="coerce")
    df["pagador"] = df["pagador"].map(N.clave)
    _fechas(df, ["fecha_pago"], ruta, campania, hallazgos)
    df["campania"] = campania
    return df.drop(columns=["referencia"])


def leer_todo(carpeta: Path) -> Lectura:
    """Lee crudo/<campaña>/ para todas las campañas del catálogo."""
    hallazgos: list[dict] = []
    partes = {"inscripciones": [], "interesados": [], "pagos": [], "vacantes": []}
    lectores = {"inscripciones": ("admision_inscripciones_{c}.csv", leer_inscripciones),
                "interesados": ("crm_interesados_{c}.xlsx", leer_interesados),
                "pagos": ("tesoreria_pagos_{c}.xlsx", leer_pagos)}
    for c in K.CAMPANIAS:
        base = Path(carpeta) / c
        for tipo, (patron, lector) in lectores.items():
            ruta = base / patron.format(c=c)
            if not ruta.exists():
                _hallazgo(hallazgos, ruta, c, "archivo_faltante", "error", "no llegó el archivo")
                continue
            df = lector(ruta, c, hallazgos)
            if df is not None:
                partes[tipo].append(df)
        ruta_vac = base / f"vacantes_{c}.csv"
        if ruta_vac.exists():
            vac = pd.read_csv(ruta_vac)
            vac["carrera"] = N.mapear_catalogo(vac["carrera"], K.CARRERAS)
            vac["sede"] = N.mapear_catalogo(vac["sede"], K.SEDES)
            vac["campania"] = c
            partes["vacantes"].append(vac)
        else:
            _hallazgo(hallazgos, ruta_vac, c, "archivo_faltante", "error", "no llegó el archivo de vacantes")

    def unir(lista, columnas):
        return pd.concat(lista, ignore_index=True) if lista else pd.DataFrame(columns=columnas)

    return Lectura(
        inscripciones=unir(partes["inscripciones"], list(K.SINONIMOS["inscripciones"]) + ["fila_archivo", "es_prueba", "campania"]),
        interesados=unir(partes["interesados"], list(K.SINONIMOS["interesados"]) + ["campania"]),
        pagos=unir(partes["pagos"], ["fecha_pago", "documento_pagador", "doc_sin_ceros", "pagador", "concepto",
                                     "tipo_pago", "referencia_codigo", "monto", "campania"]),
        vacantes=unir(partes["vacantes"], ["carrera", "sede", "vacantes", "campania"]),
        hallazgos=hallazgos,
    )
