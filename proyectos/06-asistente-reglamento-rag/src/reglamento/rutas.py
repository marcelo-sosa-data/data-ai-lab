"""Rutas por defecto (se pueden cambiar con variables de entorno)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def ruta_datos() -> Path:
    return Path(os.getenv("REGLAMENTO_DATOS", RAIZ / "datos"))


def ruta_corpus() -> Path:
    return ruta_datos() / "corpus"


def ruta_preguntas() -> Path:
    return ruta_datos() / "preguntas.json"


def ruta_resultados() -> Path:
    return ruta_datos() / "resultados"


def ruta_vectores(modelo: str) -> Path:
    return ruta_datos() / "indice" / f"{modelo.replace('/', '__')}.npz"
