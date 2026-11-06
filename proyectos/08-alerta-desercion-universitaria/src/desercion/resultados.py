"""Lectura y escritura de resultados en DuckDB (lo que lee el tablero)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def guardar(ruta: Path, tablas: dict[str, pd.DataFrame]) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in tablas.items():
            df = df.copy()
            for c in df.columns:
                if isinstance(df[c].dtype, pd.CategoricalDtype):
                    df[c] = df[c].astype(str)
            con.register("t", df)
            con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM t")
            con.unregister("t")
    finally:
        con.close()


def leer(ruta: Path, nombre: str) -> pd.DataFrame:
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {nombre}").df()
    finally:
        con.close()


def tablas(ruta: Path) -> set[str]:
    if not Path(ruta).exists():
        return set()
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()
