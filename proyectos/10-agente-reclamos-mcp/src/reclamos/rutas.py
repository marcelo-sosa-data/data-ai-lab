"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_db() -> Path:
    return Path(os.getenv("RECLAMOS_DB", RAIZ / "datos" / "killa.duckdb"))


def ruta_resultados() -> Path:
    return Path(os.getenv("RECLAMOS_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))
