"""Aplicación de Quix Streams que convierte eventos en métricas por zona.

    eventos ─ dedup por evento_id ─┬─ cola de pedidos sin motorizado (estado)
                                   │    ─ foto en cada cambio de minuto
                                   │    ─ regla de saturación ─ alertas
                                   └─ ventana de 1 min por zona con gracia
                                        ─ métricas por minuto

La clave del mensaje es la zona, así que todo el estado (ids vistos,
cola, ventanas, rachas de la regla) vive por zona y se reparte con las
particiones. La alerta no pasa por la ventana: la cola es estado y se lee
al momento, así la gracia solo retrasa las métricas por minuto.
"""

from __future__ import annotations

from pathlib import Path

from quixstreams import Application
from quixstreams.models import TopicConfig

from .agregados import (acumular, actualizar_pendientes, agregado_inicial, es_evento_nuevo,
                        estado_inicial, evaluar_minuto, fila_minuto, minuto_nuevo, sin_motorizado)
from .config import Ajustes
from .sumideros import RegistroTardios, SinkParquet


def construir(aj: Ajustes, grupo: str, salida: Path, publicar: bool = True):
    """Arma la aplicación. Devuelve (app, registro de tardíos)."""
    regla = aj.regla
    tardios = RegistroTardios(salida / "tardios")
    app = Application(
        broker_address=aj.broker,
        consumer_group=grupo,
        auto_offset_reset="earliest",
        state_dir=str(aj.dir_estado / grupo),
        commit_interval=2.0,
        loglevel="WARNING",
    )
    cfg = TopicConfig(num_partitions=aj.topicos.particiones, replication_factor=1,
                      extra_config={"retention.ms": "-1"})
    t_eventos = app.topic(aj.topicos.eventos, value_deserializer="json",
                          key_deserializer="str", config=cfg)

    def dedup(evento: dict, estado) -> bool:
        return es_evento_nuevo(estado, evento["evento_id"])

    def cola(evento: dict, clave, ts, headers, estado) -> dict | None:
        """Actualiza la cola de la zona; al cambiar de minuto devuelve una foto."""
        reloj = evento["recibido_ms"]
        pend, cerrados = estado.get("pendientes") or {}, estado.get("cerrados") or {}
        actualizar_pendientes(pend, cerrados, evento, reloj, regla.pendiente_vencido_s)
        estado.set("pendientes", pend)
        estado.set("cerrados", cerrados)
        corte = minuto_nuevo(estado.get("ultimo_corte"), reloj)
        if corte is None:
            return None
        estado.set("ultimo_corte", corte)
        return {"zona": clave, "inicio_ms": corte, "emitido_ms": reloj,
                "sin_motorizado": sin_motorizado(pend, corte, regla.espera_sin_motorizado_s)}

    def regla_zona(foto: dict, estado):
        est = estado.get("regla") or estado_inicial()
        alerta = evaluar_minuto(est, foto, regla, foto["emitido_ms"])
        estado.set("regla", est)
        return alerta

    def a_fila(ventana: dict, clave, ts, headers) -> dict:
        fila = fila_minuto(clave, ventana["start"], ventana["end"], ventana["value"])
        fila["emitido_ms"] = int(ts_ultimo.get(clave, ventana["end"]))
        return fila

    # hora de llegada del último mensaje de cada zona: con eso se sabe en qué
    # momento se cerró cada ventana (el procesador corre en un solo hilo)
    ts_ultimo: dict = {}

    def marcar_llegada(evento: dict, clave, ts, headers) -> None:
        ts_ultimo[clave] = evento["recibido_ms"]

    sdf = app.dataframe(t_eventos)
    sdf = sdf.update(marcar_llegada, metadata=True)
    sdf = sdf.filter(dedup, stateful=True)

    fotos = sdf.apply(cola, metadata=True, stateful=True).filter(lambda f: f is not None)
    alertas = fotos.apply(regla_zona, stateful=True).filter(lambda a: a is not None)

    minutos = (
        sdf.tumbling_window(aj.ventana_ms, grace_ms=aj.gracia_ms, on_late=tardios)
        .reduce(reducer=lambda agg, ev: acumular(agg, ev, regla.demora_s),
                initializer=lambda ev: agregado_inicial(ev, regla.demora_s))
        .final()
        .apply(a_fila, metadata=True)
    )

    if publicar:
        minutos.to_topic(app.topic(aj.topicos.minuto, value_serializer="json",
                                   key_serializer="str", config=cfg))
        alertas.to_topic(app.topic(aj.topicos.alertas, value_serializer="json",
                                   key_serializer="str", config=cfg))
    minutos.sink(SinkParquet(salida / "minutos", al_escribir=tardios.volcar))
    fotos.sink(SinkParquet(salida / "cola"))
    alertas.sink(SinkParquet(salida / "alertas"))
    return app, tardios


def correr(aj: Ajustes, grupo: str, salida: Path, publicar: bool = True,
           espera_s: float = 0.0) -> int:
    """Procesa el tópico. Con `espera_s` > 0 se detiene tras ese tiempo sin
    mensajes nuevos (modo repetición); con 0 corre hasta Ctrl+C."""
    app, tardios = construir(aj, grupo, salida, publicar)
    app.run(timeout=espera_s)
    tardios.volcar()
    return tardios.total
