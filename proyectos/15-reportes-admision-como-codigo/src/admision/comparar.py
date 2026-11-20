"""El reporte actual y el nuevo contra la verdad del generador."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from . import catalogos as K
from .regla_actual import reporte


def cifras(con: duckdb.DuckDBPyConnection, carpeta_crudo: Path, carpeta_verdad: Path) -> pd.DataFrame:
    """Una fila por campaña y medida con lo que dice cada reporte y lo que pasó."""
    kpi = con.sql("SELECT * FROM kpi_campania").df().set_index("campania")
    filas = []
    for c in K.CAMPANIAS:
        actual = reporte(Path(carpeta_crudo) / c, c)
        v = pd.read_parquet(Path(carpeta_verdad) / f"{c}.parquet")
        verdad = {"postulantes": int(v["postulo"].sum()), "ingresantes": int(v["ingreso"].sum()),
                  "matriculados": int((v["ingreso"] & v["matriculado"]).sum()), "interesados": None}
        for medida in ("interesados", "postulantes", "ingresantes", "matriculados"):
            filas.append({"campania": c, "medida": medida, "as_is": getattr(actual, medida),
                          "to_be": int(kpi.loc[c, medida]), "verdad": verdad[medida]})
    df = pd.DataFrame(filas)
    df["error_as_is"] = df["as_is"] / df["verdad"] - 1
    df["error_to_be"] = df["to_be"] / df["verdad"] - 1
    return df


def pendientes(con: duckdb.DuckDBPyConnection, carpeta_crudo: Path, carpeta_verdad: Path,
               campania: str = K.CAMPANIA_ACTUAL) -> pd.DataFrame:
    """
    De la lista de ingresantes por llamar que arma cada reporte, cuántos ya
    habían pagado la matrícula y cuántos ni siquiera son personas reales.
    """
    v = pd.read_parquet(Path(carpeta_verdad) / f"{campania}.parquet")
    pagaron = set(v.loc[v["matriculado"], "codigo_ingreso"].dropna())
    reales = set(v["codigo_ingreso"].dropna())
    listas = {
        "as_is": reporte(Path(carpeta_crudo) / campania, campania).pendientes["codigo"],
        "to_be": con.sql("SELECT codigo_postulante FROM pendientes_matricula").df()["codigo_postulante"],
    }
    filas = []
    for cual, codigos in listas.items():
        codigos = codigos.astype(str)
        filas.append({
            "reporte": cual, "en_lista": len(codigos),
            "ya_pagaron": int(codigos.isin(pagaron).sum()),
            "no_son_ingresantes_reales": int((~codigos.isin(reales)).sum()),
            "repetidos": int(codigos.duplicated().sum()),
        })
    df = pd.DataFrame(filas)
    df["llamadas_inutiles"] = df["ya_pagaron"] + df["no_son_ingresantes_reales"] + df["repetidos"]
    df["pct_inutiles"] = df["llamadas_inutiles"] / df["en_lista"]
    return df


def proyeccion(con: duckdb.DuckDBPyConnection, carpeta_verdad: Path,
               campania: str = K.CAMPANIA_ACTUAL) -> pd.DataFrame:
    """Matriculados proyectados por sede contra cómo termina de verdad la campaña."""
    ruta = Path(carpeta_verdad) / f"{campania}_cierre.parquet"
    proy = con.sql("""
        SELECT sede, sum(vacantes) AS vacantes, sum(matriculados) AS matriculados_hoy,
               sum(matriculados_proyectados) AS proyectados
        FROM proyeccion_vacantes GROUP BY sede
    """).df()
    if not ruta.exists():
        proy["al_cierre"] = None
        return proy
    v = pd.read_parquet(ruta)
    cierre = v[v["ingreso"] & v["matriculado"]].groupby("sede").size().rename("al_cierre")
    proy = proy.merge(cierre, left_on="sede", right_index=True, how="left")
    proy["error"] = proy["proyectados"] / proy["al_cierre"] - 1
    proy["cobertura_proyectada"] = proy["proyectados"] / proy["vacantes"]
    proy["cobertura_al_cierre"] = proy["al_cierre"] / proy["vacantes"]
    return proy
