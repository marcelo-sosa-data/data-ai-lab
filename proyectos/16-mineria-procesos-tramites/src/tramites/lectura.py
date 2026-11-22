"""
Lectura de los dos exports del sistema de trámites.

El export cambia de forma entre descargas, así que las columnas se ubican
por nombre (con sinónimos) y no por posición. Las actividades llegan en
mayúsculas y a veces sin tildes; se llevan al nombre del catálogo.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import catalogos as K

SINONIMOS_LOG = {
    "id_tramite": ["nro_tramite", "n_tramite", "id_tramite", "tramite", "nro tramite"],
    "actividad": ["actividad", "tarea", "accion"],
    "area": ["area", "unidad", "dependencia"],
    "usuario": ["usuario", "responsable", "user"],
    "inicio": ["f_inicio", "fecha_inicio", "inicio"],
    "fin": ["f_fin", "fecha_fin", "fin", "fecha"],
}
SINONIMOS_TRAMITES = {
    "id_tramite": ["nro_tramite", "n_tramite", "id_tramite", "tramite"],
    "tipo": ["tipo", "tipo_tramite"],
    "codigo_alumno": ["cod_alumno", "codigo_alumno", "codigo", "cod_estudiante"],
    "nombre_alumno": ["alumno", "nombre_alumno", "estudiante", "nombres"],
    "carrera": ["carrera", "programa"],
    "sede": ["sede", "campus"],
    "n_cursos": ["nro_cursos", "n_cursos", "cursos"],
    "origen": ["origen", "procedencia"],
    "becado": ["beca", "becado"],
    "registro": ["f_registro", "fecha_registro", "registro"],
}


def _clave(texto: str) -> str:
    """Minúsculas, sin tildes ni espacios sobrantes: para comparar nombres."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(t.lower().replace("_", " ").split())


_ACTIVIDADES = {_clave(v): v for k, v in vars(K).items()
                if k.isupper() and isinstance(v, str) and v[:1].isupper() and " " in v}
_AREAS = {_clave(a): a for a in K.AREAS + [K.SISTEMA]}
_TIPOS = {_clave(K.CONVALIDACION): K.CONVALIDACION, _clave(K.RETIRO): K.RETIRO}


def _renombrar(df: pd.DataFrame, sinonimos: dict, archivo: str) -> pd.DataFrame:
    columnas = {_clave(c): c for c in df.columns}
    mapa, faltan = {}, []
    for destino, opciones in sinonimos.items():
        origen = next((columnas[_clave(o)] for o in opciones if _clave(o) in columnas), None)
        if origen is None:
            faltan.append(destino)
        else:
            mapa[origen] = destino
    obligatorias = {"id_tramite", "actividad", "fin"} if archivo == "log" else {"id_tramite", "tipo", "registro"}
    if obligatorias & set(faltan):
        raise ValueError(f"Al export {archivo} le faltan columnas: {sorted(obligatorias & set(faltan))}")
    return df.rename(columns=mapa)[list(mapa.values())]


def _fecha(serie: pd.Series) -> pd.Series:
    """Fechas del sistema: día/mes/año. Si viene ISO también se lee, nunca mes/día."""
    s = serie.astype("string").str.strip().replace("", pd.NA)
    f = pd.to_datetime(s, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    resto = f.isna() & s.notna()
    if resto.any():
        f[resto] = pd.to_datetime(s[resto], format="ISO8601", errors="coerce")
    return f


@dataclass
class Log:
    eventos: pd.DataFrame
    tramites: pd.DataFrame
    hallazgos: dict = field(default_factory=dict)


def leer(carpeta: str | Path) -> Log:
    carpeta = Path(carpeta)
    crudo = pd.read_csv(carpeta / "log_tramites.csv", sep=None, engine="python", dtype=str,
                        encoding="utf-8-sig", keep_default_na=False)
    ev = _renombrar(crudo, SINONIMOS_LOG, "log")
    ev["id_tramite"] = ev["id_tramite"].str.strip().str.upper()
    claves = ev["actividad"].map(_clave)
    desconocidas = sorted(set(claves) - set(_ACTIVIDADES))
    ev["actividad"] = claves.map(_ACTIVIDADES)
    ev["area"] = ev["area"].map(lambda a: _AREAS.get(_clave(a), a))
    ev["usuario"] = ev.get("usuario", pd.Series("", index=ev.index)).str.strip().str.lower()
    ev["inicio"] = _fecha(ev["inicio"]) if "inicio" in ev else pd.NaT
    ev["fin"] = _fecha(ev["fin"])

    n = len(ev)
    ev = ev[ev["actividad"].notna() & ev["fin"].notna()]
    sin_leer = n - len(ev)
    n = len(ev)
    ev = ev.drop_duplicates(["id_tramite", "actividad", "inicio", "fin"])
    duplicados = n - len(ev)
    ev = ev.sort_values(["id_tramite", "fin"], kind="stable").reset_index(drop=True)
    ev["orden"] = ev.groupby("id_tramite").cumcount()

    crudo_t = pd.read_csv(carpeta / "tramites.csv", sep=None, engine="python", dtype=str,
                          encoding="utf-8-sig", keep_default_na=False)
    tr = _renombrar(crudo_t, SINONIMOS_TRAMITES, "tramites")
    tr["id_tramite"] = tr["id_tramite"].str.strip().str.upper()
    tr["tipo"] = tr["tipo"].map(lambda t: _TIPOS.get(_clave(t), t))
    # el código se queda como texto: algunos empiezan con letra y otros con cero
    tr["codigo_alumno"] = tr["codigo_alumno"].astype("string").str.strip().str.upper()
    tr["nombre_alumno"] = tr["nombre_alumno"].str.strip().str.title()
    tr["n_cursos"] = pd.to_numeric(tr.get("n_cursos"), errors="coerce").astype("Int64")
    tr["origen"] = tr.get("origen", "").replace("", None)
    tr["becado"] = tr.get("becado", "NO").str.strip().str.upper().isin(["SI", "SÍ", "S", "1", "TRUE"])
    tr["registro"] = _fecha(tr["registro"])
    tr = tr.drop_duplicates("id_tramite").reset_index(drop=True)

    cierre = ev[ev["actividad"].isin([K.NOTIFICAR, K.ARCHIVAR])].groupby("id_tramite")["fin"].max()
    archivados = set(ev.loc[ev["actividad"] == K.ARCHIVAR, "id_tramite"])
    rechazados = set(ev.loc[ev["actividad"].isin([K.RECHAZAR_EXT, K.RECHAZAR_DIR]), "id_tramite"])
    tr["fin"] = tr["id_tramite"].map(cierre)
    tr["estado"] = "Abierto"
    tr.loc[tr["fin"].notna(), "estado"] = "Atendido"
    tr.loc[tr["id_tramite"].isin(rechazados) & tr["fin"].notna(), "estado"] = "Rechazado"
    tr.loc[tr["id_tramite"].isin(archivados), "estado"] = "Archivado"

    hallazgos = {
        "eventos": len(ev), "duplicados": duplicados, "sin_leer": sin_leer,
        "actividades_desconocidas": desconocidas,
        "sin_hora_inicio": int(ev["inicio"].isna().sum()),
        "eventos_sin_tramite": int((~ev["id_tramite"].isin(tr["id_tramite"])).sum()),
        "abiertos": int((tr["estado"] == "Abierto").sum()),
    }
    return Log(ev, tr, hallazgos)
