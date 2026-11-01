"""Punto de entrada de la capa semántica: cargar el YAML, compilar y ejecutar."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .compilador import Compilador, Consulta
from .modelo import Definicion, cargar
from .rutas import ruta_db, ruta_semantica


class CapaSemantica:
    def __init__(self, definicion: Definicion):
        self.definicion = definicion
        self.compilador = Compilador(definicion)

    @classmethod
    def desde_yaml(cls, ruta: str | Path | None = None) -> "CapaSemantica":
        return cls(cargar(ruta or ruta_semantica()))

    def sql(self, consulta: Consulta, dialecto: str = "duckdb") -> str:
        return self.compilador.compilar(consulta, dialecto)

    def consultar(self, con: duckdb.DuckDBPyConnection, consulta: Consulta) -> pd.DataFrame:
        df = con.execute(self.compilador.compilar(consulta, legible=False)).df()
        if "periodo" in df:
            df["periodo"] = pd.to_datetime(df["periodo"])
        return df


def conectar(ruta: Path | None = None) -> duckdb.DuckDBPyConnection:
    ruta = Path(ruta or ruta_db())
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}. Corre primero: python -m kpis generar")
    return duckdb.connect(str(ruta), read_only=True)
