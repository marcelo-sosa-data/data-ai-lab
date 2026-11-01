"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_db() -> Path:
    return Path(os.getenv("TINKUY_DB", RAIZ / "datos" / "tinkuy.duckdb"))


def ruta_resultados() -> Path:
    return Path(os.getenv("TINKUY_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))


def ruta_semantica() -> Path:
    return Path(os.getenv("TINKUY_SEMANTICA", RAIZ / "semantica" / "tinkuy.yml"))
