"""Escritura y lectura de resultados.duckdb, que es lo que lee el tablero."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def guardar(ruta: Path, tablas: dict[str, pd.DataFrame]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in tablas.items():
            con.register("_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM _df")
            con.unregister("_df")
    finally:
        con.close()


def leer_tabla(ruta: Path, nombre: str) -> pd.DataFrame:
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {nombre}").df()
    finally:
        con.close()
