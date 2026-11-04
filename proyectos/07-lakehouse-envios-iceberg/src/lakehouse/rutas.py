"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def dir_datos() -> Path:
    return Path(os.getenv("KALLPA_DATOS", RAIZ / "datos"))


def dir_cdc() -> Path:
    return dir_datos() / "cdc"


def dir_lakehouse() -> Path:
    return dir_datos() / "lakehouse"


def ruta_origen() -> Path:
    return dir_datos() / "origen" / "envios.parquet"


def ruta_bitacora() -> Path:
    return dir_datos() / "bitacora.duckdb"


def ruta_contrato() -> Path:
    return Path(os.getenv("KALLPA_CONTRATO", RAIZ / "contratos" / "envios.yml"))
