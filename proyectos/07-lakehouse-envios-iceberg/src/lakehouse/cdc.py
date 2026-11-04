"""Lectura de los archivos que deja el conector CDC (JSON por línea, gzip, una carpeta por lote)."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa

from .calendario import corte_de
from .catalogo import ESQUEMA_BRONCE
from .rutas import dir_cdc

ARROW_BRONCE = ESQUEMA_BRONCE.as_arrow()
LIMA = timezone(timedelta(hours=-5))


def lotes_disponibles(directorio: Path | None = None) -> list[str]:
    d = Path(directorio or dir_cdc())
    if not d.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in d.glob("lote=*") if p.is_dir())


def _hora_lima(ts_ms: int) -> datetime:
    """ts_ms viene en UTC; el resto de la base trabaja en hora de Lima sin zona."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(LIMA).replace(tzinfo=None)


def leer_lote(lote: str, directorio: Path | None = None) -> pa.Table:
    """Todas las líneas del lote, en el orden en que llegaron (archivo, línea)."""
    carpeta = Path(directorio or dir_cdc()) / f"lote={lote}"
    fecha = corte_de(lote).date()
    filas = []
    for archivo in sorted(carpeta.glob("*.jsonl.gz")):
        with gzip.open(archivo, "rt", encoding="utf-8") as fh:
            for n, linea in enumerate(fh, start=1):
                e = json.loads(linea)
                img = e.get("despues") or e.get("antes") or {}
                filas.append({
                    "lote": lote, "archivo": archivo.name, "linea": n, "lsn": e["lsn"], "op": e["op"],
                    "ts_commit": _hora_lima(e["ts_ms"]), "id_envio": img.get("id_envio"),
                    "antes": json.dumps(e["antes"], ensure_ascii=False) if e.get("antes") else None,
                    "despues": json.dumps(e["despues"], ensure_ascii=False) if e.get("despues") else None,
                    "fecha_lote": fecha,
                })
    return pa.Table.from_pylist(filas, schema=ARROW_BRONCE)
