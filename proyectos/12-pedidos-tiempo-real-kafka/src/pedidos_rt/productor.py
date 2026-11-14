"""Repite los eventos generados contra el broker, en el orden en que llegaron.

El mensaje lleva como timestamp la hora del evento (lo que usan las
ventanas) y en el cuerpo la hora en que llegó (`recibido_ms`). Como se
publican en orden de llegada, un evento atrasado entra al tópico después
de eventos más nuevos, igual que en producción.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from .config import Ajustes


def a_ms(serie: pd.Series) -> pd.Series:
    """Hora de Lima sin zona horaria a milisegundos (se trata como UTC)."""
    return serie.astype("datetime64[ms]").astype("int64")


def mensajes(ruta_eventos: Path) -> pd.DataFrame:
    ev = pd.read_parquet(ruta_eventos).sort_values(["ts_recibido", "evento_id"])
    ev["ts_ms"] = a_ms(ev["ts_evento"])
    ev["recibido_ms"] = a_ms(ev["ts_recibido"])
    return ev.reset_index(drop=True)


def cuerpo(fila) -> bytes:
    espera = fila.espera_asignacion_s
    return json.dumps({
        "evento_id": fila.evento_id,
        "pedido_id": fila.pedido_id,
        "zona": fila.zona,
        "tipo": fila.tipo,
        "ts_ms": int(fila.ts_ms),
        "recibido_ms": int(fila.recibido_ms),
        "espera_asignacion_s": None if pd.isna(espera) else float(espera),
    }, ensure_ascii=False).encode("utf-8")


def preparar_topicos(aj: Ajustes, reiniciar: bool = False) -> None:
    admin = AdminClient({"bootstrap.servers": aj.broker})
    nombres = [aj.topicos.eventos, aj.topicos.minuto, aj.topicos.alertas]
    existentes = set(admin.list_topics(timeout=10).topics)
    if reiniciar:
        borrar = [n for n in nombres if n in existentes]
        if borrar:
            for f in admin.delete_topics(borrar).values():
                f.result()
            time.sleep(2)
            existentes -= set(borrar)
    # la semana simulada tiene fechas pasadas: sin retención por tiempo el
    # broker borraría los segmentos apenas los escribe
    nuevos = [NewTopic(n, num_partitions=aj.topicos.particiones, replication_factor=1,
                       config={"retention.ms": "-1"})
              for n in nombres if n not in existentes]
    if nuevos:
        for f in admin.create_topics(nuevos).values():
            f.result()


def publicar(aj: Ajustes, ruta_eventos: Path, velocidad: float = 0.0,
             limite: int | None = None) -> int:
    """Publica los eventos. `velocidad` = 60 repite una hora en un minuto; 0 = sin pausas."""
    ev = mensajes(ruta_eventos)
    if limite:
        ev = ev.head(limite)
    prod = Producer({"bootstrap.servers": aj.broker, "linger.ms": 20,
                     "compression.type": "lz4", "enable.idempotence": True})
    inicio_real = time.monotonic()
    inicio_sim = int(ev["recibido_ms"].iloc[0]) if len(ev) else 0
    for i, fila in enumerate(ev.itertuples(index=False)):
        if velocidad > 0:
            objetivo = (fila.recibido_ms - inicio_sim) / 1000 / velocidad
            pausa = objetivo - (time.monotonic() - inicio_real)
            if pausa > 0:
                time.sleep(pausa)
        prod.produce(aj.topicos.eventos, key=fila.zona.encode("utf-8"), value=cuerpo(fila),
                     timestamp=int(fila.ts_ms))
        if i % 5000 == 0:
            prod.poll(0)
    prod.flush(30)
    return len(ev)
