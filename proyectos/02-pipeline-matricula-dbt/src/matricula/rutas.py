"""Rutas por defecto del proyecto. Se pueden cambiar con MATRICULA_RAW y MATRICULA_DB."""

from __future__ import annotations

import json
import os
from pathlib import Path

RAIZ = Path(__file__).parents[2]
DIR_DBT = RAIZ / "dbt_matricula"
RAW_DEFECTO = RAIZ / "datos" / "raw"
DB_DEFECTO = RAIZ / "datos" / "universidad.duckdb"


def ruta_raw() -> Path:
    return Path(os.getenv("MATRICULA_RAW", RAW_DEFECTO)).resolve()


def ruta_db() -> Path:
    return Path(os.getenv("MATRICULA_DB", DB_DEFECTO)).resolve()


def leer_manifiesto(raw: Path | None = None) -> dict:
    """Metadatos del export: fecha de corte, periodos y anomalías inyectadas."""
    ruta = (raw or ruta_raw()) / "_anomalias.json"
    if not ruta.exists():
        raise FileNotFoundError(f"No hay export en {ruta.parent}. Corre primero: python -m matricula generar")
    return json.loads(ruta.read_text(encoding="utf-8"))
