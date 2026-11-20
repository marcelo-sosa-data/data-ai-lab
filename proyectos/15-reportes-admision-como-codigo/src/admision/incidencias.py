"""
Incidencias sembradas en los exports de la campaña en curso.

Cada una es algo que ya pasó o que pasa seguido con estos archivos: una
columna nueva, un nombre de carrera que cambia, un export que se cortó, una
carga de prueba en producción. Se aplica sobre una copia de los datos y se
corren los dos procesos:

  - el reporte actual, que publica lo que salga
  - el nuevo, que publica solo si las pruebas de datos no tienen errores

y se compara lo que cada uno publicaría contra lo que publica sin la
incidencia.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from . import catalogos as K
from .lectura import leer_todo
from .modelo import construir
from .pruebas import correr, hay_bloqueo
from .regla_actual import reporte

C = K.CAMPANIA_ACTUAL


def _adm(d: Path) -> Path:
    return d / f"admision_inscripciones_{C}.csv"


def _crm(d: Path) -> Path:
    return d / f"crm_interesados_{C}.xlsx"


def _tes(d: Path) -> Path:
    return d / f"tesoreria_pagos_{C}.xlsx"


def _editar_adm(d: Path, f: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    df = pd.read_csv(_adm(d), dtype=str, keep_default_na=False)
    f(df).to_csv(_adm(d), index=False, encoding="utf-8")


def _editar_xlsx(ruta: Path, f: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    df = pd.read_excel(ruta, dtype=object)
    f(df).to_excel(ruta, index=False)


def _filas_reales(df: pd.DataFrame) -> pd.Series:
    return ~df["nombre_completo"].str.contains("PRUEBA", na=False)


def _columna_nueva(d):
    def f(df):
        df.insert(4, "correo", [f"postulante{i}@correo.pe" for i in range(len(df))])
        return df
    _editar_adm(d, f)


def _encabezado_renombrado(d):
    _editar_adm(d, lambda df: df.rename(columns={"documento": "doc_identidad"}))


def _modalidad_nueva(d):
    def f(df):
        idx = df[_filas_reales(df)].sample(40, random_state=1).index
        df.loc[idx, "modalidad_ingreso"] = "CONVENIO EMPRESAS"
        return df
    _editar_adm(d, f)


def _carrera_renombrada(d):
    def f(df):
        df["carrera"] = df["carrera"].replace("INGENIERIA DE SISTEMAS", "INGENIERIA DE SISTEMAS E INFORMATICA")
        return df
    _editar_adm(d, f)


def _crm_duplicado(d):
    _editar_xlsx(_crm(d), lambda df: pd.concat([df, df], ignore_index=True))


def _admision_incompleta(d):
    _editar_adm(d, lambda df: df[df["fecha_inscripcion"] <= "2026-11-08 23:59:59"])


def _pruebas_masivas(d):
    def f(df):
        base = df[_filas_reales(df)].sample(300, replace=True, random_state=2).copy()
        base["codigo_postulante"] = [f"{C.replace('-', '')}8{i:04d}" for i in range(300)]
        base["nombre_completo"] = [f"PRUEBA CARGA MASIVA {i}" for i in range(300)]
        base["documento"] = [f"7{i:07d}" for i in range(300)]
        base["estado"] = "INSCRITO"
        base[["puntaje", "fecha_resultado"]] = ""
        return pd.concat([df, base], ignore_index=True)
    _editar_adm(d, f)


def _ingreso_sin_evaluacion(d):
    def f(df):
        idx = df[_filas_reales(df) & (df["estado"] == "INSCRITO")].sample(40, random_state=3).index
        df.loc[idx, "estado"] = "INGRESO"
        return df
    _editar_adm(d, f)


def _fechas_mes_dia(d):
    def f(df):
        fechas = pd.to_datetime(df["fecha_inscripcion"])
        df["fecha_inscripcion"] = fechas.dt.strftime("%m/%d/%Y %H:%M")
        return df
    _editar_adm(d, f)


def _documento_como_numero(d):
    def f(df):
        dni = df["tipo_documento"] == "DNI"
        df.loc[dni, "documento"] = df.loc[dni, "documento"].str.strip().str.lstrip("0")
        return df
    _editar_adm(d, f)


def _resultados_revertidos(d):
    def f(df):
        idx = df[_filas_reales(df) & (df["estado"] == "INGRESO")].sample(25, random_state=4).index
        df.loc[idx, "estado"] = "NO INGRESO"
        return df
    _editar_adm(d, f)


def _concepto_con_tilde(d):
    def f(df):
        df["Concepto"] = df["Concepto"].str.replace("MATRICULA", "MATRÍCULA", regex=False)
        return df
    _editar_xlsx(_tes(d), f)


def _referencia_vacia(d):
    def f(df):
        df["Referencia"] = None
        return df
    _editar_xlsx(_tes(d), f)


def _tesoreria_atrasada(d):
    _editar_xlsx(_tes(d), lambda df: df[pd.to_datetime(df["Fecha"]) < "2026-11-02"])


def _crm_vacio(d):
    _editar_xlsx(_crm(d), lambda df: df.iloc[0:0])


@dataclass(frozen=True)
class Incidencia:
    nombre: str
    descripcion: str
    aplicar: Callable[[Path], None]


INCIDENCIAS = [
    Incidencia("columna_nueva", "El sistema de admisión agrega la columna correo en medio del export", _columna_nueva),
    Incidencia("encabezado_renombrado", "La columna documento pasa a llamarse doc_identidad", _encabezado_renombrado),
    Incidencia("modalidad_nueva", "Aparece la modalidad Convenio empresas en 40 inscripciones", _modalidad_nueva),
    Incidencia("carrera_renombrada", "Ingeniería de Sistemas pasa a llamarse Ingeniería de Sistemas e Informática", _carrera_renombrada),
    Incidencia("documento_como_numero", "El export de admisión pierde los ceros a la izquierda del DNI", _documento_como_numero),
    Incidencia("fechas_mes_dia", "Las fechas de inscripción salen como mes/día/año", _fechas_mes_dia),
    Incidencia("admision_incompleta", "El export de admisión se corta y llega solo hasta el 8 de noviembre", _admision_incompleta),
    Incidencia("pruebas_masivas", "Sistemas deja 300 inscripciones de una prueba de carga en producción", _pruebas_masivas),
    Incidencia("ingreso_sin_evaluacion", "Una actualización masiva marca como ingresantes a 40 inscritos sin resultado", _ingreso_sin_evaluacion),
    Incidencia("resultados_revertidos", "Una actualización masiva cambia 25 ingresos a no ingresó", _resultados_revertidos),
    Incidencia("concepto_con_tilde", "Tesorería empieza a escribir MATRÍCULA con tilde en el concepto", _concepto_con_tilde),
    Incidencia("referencia_vacia", "Tesorería deja de llenar la referencia con el código de postulante", _referencia_vacia),
    Incidencia("tesoreria_atrasada", "El reporte de tesorería llega con pagos solo hasta el 1 de noviembre", _tesoreria_atrasada),
    Incidencia("crm_duplicado", "El export del CRM sale con todas las filas dos veces", _crm_duplicado),
    Incidencia("crm_vacio", "El export del CRM llega solo con encabezados", _crm_vacio),
]


def _cifras_nuevo(carpeta: Path) -> tuple[dict, list]:
    con = construir(leer_todo(carpeta))
    resultados = correr(con)
    kpi = con.sql(f"SELECT * FROM kpi_campania WHERE campania = '{C}'").df().iloc[0]
    cifras = {m: int(kpi[m]) for m in ("interesados", "postulantes", "ingresantes", "matriculados")}
    for dim, col in (("modalidad", "modalidad_primera"), ("sede", "sede"), ("carrera", "carrera")):
        df = con.sql(f"SELECT {col} AS v, count(*) AS n FROM postulantes WHERE campania = '{C}' GROUP BY 1").df()
        cifras.update({f"postulantes {dim} {r.v}": int(r.n) for r in df.itertuples()})
    con.close()
    return cifras, resultados


def _cifras_actual(carpeta: Path) -> dict:
    r = reporte(carpeta / C, C)
    cifras = {m: getattr(r, m) for m in ("interesados", "postulantes", "ingresantes", "matriculados")}
    for dim, tabla in (("modalidad", r.por_modalidad), ("sede", r.por_sede), ("carrera", r.por_carrera)):
        cifras.update({f"postulantes {dim} {v}": int(n) for v, n in zip(tabla[dim], tabla["postulantes"])})
    return cifras


def _desvio(cifras: dict, base: dict) -> tuple[float, str]:
    """Mayor diferencia relativa contra lo publicado sin incidencia, y en qué cifra."""
    peor, donde = 0.0, ""
    for k in set(base) | set(cifras):
        b, x = base.get(k, 0), cifras.get(k, 0)
        d = abs(x / b - 1) if b else (1.0 if x else 0.0)
        if d > peor + 1e-12:
            peor, donde = d, k
    return peor, donde


def evaluar(carpeta_crudo: Path, incidencias: list[Incidencia] | None = None) -> pd.DataFrame:
    carpeta_crudo = Path(carpeta_crudo)
    base_nuevo, res_base = _cifras_nuevo(carpeta_crudo)
    if hay_bloqueo(res_base):
        raise RuntimeError("los datos sin incidencias ya tienen pruebas con error; corrige eso primero")
    base_actual = _cifras_actual(carpeta_crudo)
    filas = []
    for inc in incidencias or INCIDENCIAS:
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "crudo"
            shutil.copytree(carpeta_crudo, copia)
            inc.aplicar(copia / C)
            actual = _cifras_actual(copia)
            nuevo, resultados = _cifras_nuevo(copia)
        d_act, donde_act = _desvio(actual, base_actual)
        d_nue, donde_nue = _desvio(nuevo, base_nuevo)
        bloquea = hay_bloqueo(resultados)
        fallidas = [r.nombre for r in resultados if r.bloquea]
        avisos = [r.nombre for r in resultados if not r.aprobada and not r.bloquea]
        if bloquea:
            nuevo_res = "bloquea"
        elif d_nue < 1e-12:
            nuevo_res = "absorbe"
        else:
            nuevo_res = "publica distinto"
        filas.append({
            "incidencia": inc.nombre, "descripcion": inc.descripcion,
            "actual_desvio": round(d_act, 4), "actual_cifra": donde_act if d_act > 0 else "",
            "actual_resultado": "publica distinto" if d_act > 0 else "sin efecto",
            "nuevo_resultado": nuevo_res, "nuevo_desvio_si_publicara": round(d_nue, 4),
            "nuevo_cifra": donde_nue if d_nue > 0 else "",
            "pruebas_con_error": ", ".join(fallidas), "avisos": ", ".join(avisos),
        })
    return pd.DataFrame(filas)


def resumen(df: pd.DataFrame) -> dict:
    return {
        "incidencias": len(df),
        "actual_publica_distinto": int((df["actual_resultado"] == "publica distinto").sum()),
        "actual_sutiles": int(((df["actual_desvio"] > 0) & (df["actual_desvio"] < 0.2)).sum()),
        "nuevo_bloquea": int((df["nuevo_resultado"] == "bloquea").sum()),
        "nuevo_absorbe": int((df["nuevo_resultado"] == "absorbe").sum()),
        "nuevo_publica_distinto": int((df["nuevo_resultado"] == "publica distinto").sum()),
        "desvio_medio_actual": float(np.round(df["actual_desvio"].mean(), 4)),
    }
