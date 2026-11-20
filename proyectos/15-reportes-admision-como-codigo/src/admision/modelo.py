"""Carga lo leído en DuckDB y corre los modelos SQL de sql/ en orden."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from . import catalogos as K
from .lectura import Lectura

RAIZ = Path(__file__).parents[2]
CARPETA_SQL = RAIZ / "sql"

# tablas que publica el sitio
TABLAS_REPORTE = ["kpi_campania", "embudo_modalidad", "embudo_sede_carrera", "avance_semanal",
                  "comparativo", "canales", "pendientes_matricula", "pagos_sin_asignar",
                  "proyeccion_vacantes"]


def tabla_campanias(corte_actual: date) -> pd.DataFrame:
    filas = []
    for c in K.CAMPANIAS.values():
        corte = min(c.cierre, corte_actual) if c.inicio <= corte_actual else c.cierre
        filas.append({"codigo": c.codigo, "inicio": c.inicio, "cierre": c.cierre, "corte": corte,
                      "semana_corte": (corte - c.inicio).days // 7 + 1,
                      "anterior_comparable": c.anterior_comparable})
    df = pd.DataFrame(filas)
    for col in ("inicio", "cierre", "corte"):
        df[col] = pd.to_datetime(df[col]).dt.date
    return df


def construir(lectura: Lectura, corte: date = K.CORTE_ACTUAL, campania_actual: str = K.CAMPANIA_ACTUAL,
              ruta: Path | str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(ruta))
    entradas = {
        "stg_inscripciones": lectura.inscripciones,
        "stg_interesados": lectura.interesados,
        "stg_pagos": lectura.pagos,
        "stg_vacantes": lectura.vacantes,
        "hallazgos_lectura": pd.DataFrame(lectura.hallazgos,
                                          columns=["campania", "archivo", "regla", "severidad", "detalle"]),
        "campanias": tabla_campanias(corte),
        "parametros": pd.DataFrame([{"campania_actual": campania_actual, "corte": corte}]),
        "catalogo_modalidades": pd.DataFrame({"modalidad": K.MODALIDADES}),
        "catalogo_carreras": pd.DataFrame({"carrera": K.CARRERAS}),
        "catalogo_sedes": pd.DataFrame({"sede": K.SEDES}),
        "catalogo_canales": pd.DataFrame({"canal": K.CANALES}),
    }
    for nombre, df in entradas.items():
        con.register("_tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM _tmp")
        con.unregister("_tmp")
    # las columnas de texto pueden llegar vacías y DuckDB las tipa como NULL
    con.execute("ALTER TABLE parametros ALTER corte TYPE DATE")
    for archivo in sorted(CARPETA_SQL.glob("*.sql")):
        con.execute(archivo.read_text(encoding="utf-8"))
    return con
