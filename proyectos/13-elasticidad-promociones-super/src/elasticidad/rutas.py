"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_db() -> Path:
    return Path(os.getenv("ELASTICIDAD_DB", RAIZ / "datos" / "qollqa.duckdb"))


def ruta_resultados() -> Path:
    return Path(os.getenv("ELASTICIDAD_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))


def ruta_modelos() -> Path:
    return Path(os.getenv("ELASTICIDAD_MODELOS", RAIZ / "datos" / "modelos"))
