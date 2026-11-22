"""Guarda y lee las tablas que usa el tablero, en una base DuckDB."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd


def guardar(ruta: Path, tablas: dict[str, pd.DataFrame], meta: dict | None = None) -> None:
    """Reemplaza solo las tablas que se pasan; las demás quedan como estaban."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in tablas.items():
            con.register("_df", df)
            con.execute(f'CREATE OR REPLACE TABLE "{nombre}" AS SELECT * FROM _df')
            con.unregister("_df")
        if meta:
            actual = leer_meta(con)
            actual.update(meta)
            con.execute("CREATE OR REPLACE TABLE metadatos (clave VARCHAR, valor VARCHAR)")
            con.executemany("INSERT INTO metadatos VALUES (?, ?)",
                            [(k, json.dumps(v, default=str)) for k, v in actual.items()])
    finally:
        con.close()


def leer_meta(con) -> dict:
    existe = con.execute("SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = 'metadatos'").fetchone()[0]
    if not existe:
        return {}
    return {k: json.loads(v) for k, v in con.execute("SELECT clave, valor FROM metadatos").fetchall()}


def leer(ruta: Path, tabla: str) -> pd.DataFrame:
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(f'SELECT * FROM "{tabla}"').df()
    finally:
        con.close()


def tablas(ruta: Path) -> set[str]:
    if not Path(ruta).exists():
        return set()
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    finally:
        con.close()


def meta(ruta: Path) -> dict:
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return leer_meta(con)
    finally:
        con.close()
