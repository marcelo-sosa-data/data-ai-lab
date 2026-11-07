"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_db() -> Path:
    return Path(os.getenv("COHORTES_DB", RAIZ / "datos" / "ayni.duckdb"))


def ruta_resultados() -> Path:
    return Path(os.getenv("COHORTES_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))
