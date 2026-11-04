"""Bitácora de corridas en DuckDB: una fila por lote y una por tabla en cada mantenimiento."""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pandas as pd

from .rutas import ruta_bitacora


class Bitacora:
    def __init__(self, ruta: Path | None = None):
        self.ruta = Path(ruta or ruta_bitacora())
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

    def _escribir(self, tabla: str, filas: list[dict]) -> None:
        if not filas:
            return
        df = pd.DataFrame(filas)  # noqa: F841 (DuckDB lo lee por nombre)
        for intento in range(20):  # si la app tiene la base abierta, espera un poco
            try:
                con = duckdb.connect(str(self.ruta))
                break
            except duckdb.IOException:
                if intento == 19:
                    raise
                time.sleep(0.5)
        with con:
            existe = con.sql(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{tabla}'"
                             ).fetchall()[0][0]
            if existe:
                con.sql(f"INSERT INTO {tabla} BY NAME SELECT * FROM df")
            else:
                con.sql(f"CREATE TABLE {tabla} AS SELECT * FROM df")

    def lote(self, fila: dict) -> None:
        self._escribir("lotes", [fila])

    def mantenimiento(self, filas: list[dict]) -> None:
        self._escribir("mantenimiento", filas)

    def leer(self, tabla: str) -> pd.DataFrame:
        if not self.ruta.exists():
            return pd.DataFrame()
        with duckdb.connect(str(self.ruta), read_only=True) as con:
            tablas = {r[0] for r in con.sql("SHOW TABLES").fetchall()}
            return con.sql(f"SELECT * FROM {tabla}").df() if tabla in tablas else pd.DataFrame()

    def reiniciar(self) -> None:
        self.ruta.unlink(missing_ok=True)
