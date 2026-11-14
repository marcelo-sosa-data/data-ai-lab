"""Sumidero a Parquet y registro de eventos que llegan fuera de la gracia.

Cada lote se escribe como un archivo nuevo (primero con nombre temporal y
luego renombrado), así el tablero puede leer la carpeta con DuckDB
mientras el procesador sigue escribiendo.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pandas as pd
from quixstreams.sinks import BatchingSink, SinkBatch


def escribir_parte(directorio: Path, filas: list[dict]) -> Path | None:
    if not filas:
        return None
    directorio.mkdir(parents=True, exist_ok=True)
    final = directorio / f"parte-{uuid.uuid4().hex[:12]}.parquet"
    temporal = final.with_suffix(".tmp")
    pd.DataFrame(filas).to_parquet(temporal, index=False)
    temporal.rename(final)
    return final


class SinkParquet(BatchingSink):
    """Escribe cada lote del checkpoint en una carpeta de Parquet."""

    def __init__(self, directorio: Path, al_escribir=None):
        super().__init__()
        self.directorio = Path(directorio)
        self.al_escribir = al_escribir

    def setup(self):
        self.directorio.mkdir(parents=True, exist_ok=True)

    def write(self, batch: SinkBatch):
        escribir_parte(self.directorio, [item.value for item in batch])
        if self.al_escribir:
            self.al_escribir()


class RegistroTardios:
    """Junta los eventos que llegaron después de cerrada su ventana.

    Se pasa como `on_late` a la ventana. No se pierden: quedan en
    `tardios/` para que el cierre del día los concilie.
    """

    def __init__(self, directorio: Path):
        self.directorio = Path(directorio)
        self._filas: list[dict] = []
        self._lock = threading.Lock()
        self.total = 0

    def __call__(self, value, key, timestamp_ms, late_by_ms, start, end, *args) -> bool:
        with self._lock:
            self._filas.append({
                "evento_id": value.get("evento_id"),
                "pedido_id": value.get("pedido_id"),
                "zona": key,
                "tipo": value.get("tipo"),
                "ts_evento_ms": timestamp_ms,
                "recibido_ms": value.get("recibido_ms"),
                "espera_asignacion_s": value.get("espera_asignacion_s"),
                "ventana_inicio_ms": start,
                "tarde_por_ms": late_by_ms,
            })
            self.total += 1
        return False  # sin warning en el log por cada evento

    def volcar(self):
        with self._lock:
            filas, self._filas = self._filas, []
        escribir_parte(self.directorio, filas)
