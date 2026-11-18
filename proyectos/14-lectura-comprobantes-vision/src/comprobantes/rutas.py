"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_db() -> Path:
    return Path(os.getenv("COMPROBANTES_DB", RAIZ / "datos" / "tayta.duckdb"))


def ruta_imagenes() -> Path:
    return ruta_db().parent / "imagenes"


def ruta_resultados() -> Path:
    return Path(os.getenv("COMPROBANTES_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))
