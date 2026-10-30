"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_db() -> Path:
    return Path(os.getenv("CHASQUI_DB", RAIZ / "datos" / "chasqui.duckdb"))


def ruta_resultados() -> Path:
    return Path(os.getenv("CHASQUI_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))


def ruta_reportes() -> Path:
    return Path(os.getenv("CHASQUI_REPORTES", RAIZ / "reportes"))
