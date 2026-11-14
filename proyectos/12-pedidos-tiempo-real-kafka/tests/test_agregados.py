from pedidos_rt.agregados import (EstadoDict, acumular, actualizar_pendientes, agregado_inicial,
                                  es_evento_nuevo, estado_inicial, evaluar_minuto, evaluar_serie,
                                  fila_minuto, minuto_nuevo, sin_motorizado)
from pedidos_rt.config import Regla


def ev(tipo, pid="P1", ts=0, espera=None, eid="E1"):
    return {"tipo": tipo, "pedido_id": pid, "ts_ms": ts, "espera_asignacion_s": espera,
            "evento_id": eid}


def test_agregado_por_minuto():
    agg = agregado_inicial(ev("creado"))
    agg = acumular(agg, ev("asignado", espera=400))
    agg = acumular(agg, ev("asignado", espera=100))
    agg = acumular(agg, ev("cancelado"))
    agg = acumular(agg, ev("otro"))
    assert agg["creados"] == 1 and agg["asignados"] == 2 and agg["cancelados"] == 1
    assert agg["demoradas"] == 1
    fila = fila_minuto("Surco", 0, 60_000, agg)
    assert fila["espera_media_s"] == 250.0


def test_dedup_por_id():
    estado = EstadoDict()
    assert es_evento_nuevo(estado, "E1")
    assert not es_evento_nuevo(estado, "E1")
    assert es_evento_nuevo(estado, "E2")


def test_cola_sin_motorizado():
    pend, cerr = {}, {}
    actualizar_pendientes(pend, cerr, ev("creado", "P1", ts=0), reloj_ms=0)
    actualizar_pendientes(pend, cerr, ev("creado", "P2", ts=100_000), reloj_ms=100_000)
    assert sin_motorizado(pend, corte_ms=200_000, espera_s=180) == 1     # solo P1 pasó 3 min
    actualizar_pendientes(pend, cerr, ev("asignado", "P1"), reloj_ms=210_000)
    assert sin_motorizado(pend, corte_ms=300_000, espera_s=180) == 1     # ahora P2
    assert set(pend) == {"P2"}


def test_cierre_que_llega_antes_que_el_creado():
    pend, cerr = {}, {}
    actualizar_pendientes(pend, cerr, ev("asignado", "P9"), reloj_ms=50_000)
    actualizar_pendientes(pend, cerr, ev("creado", "P9", ts=10_000), reloj_ms=60_000)
    assert pend == {}


def test_pendientes_vencidos_se_descartan():
    pend, cerr = {}, {}
    actualizar_pendientes(pend, cerr, ev("creado", "P1", ts=0), reloj_ms=0, vencido_s=600)
    actualizar_pendientes(pend, cerr, ev("creado", "P2", ts=700_000), reloj_ms=700_000, vencido_s=600)
    assert set(pend) == {"P2"}


def test_minuto_nuevo():
    assert minuto_nuevo(None, 61_500) == 60_000
    assert minuto_nuevo(60_000, 119_999) is None
    assert minuto_nuevo(60_000, 120_000) == 120_000


def _fotos(colas):
    return [{"zona": "Ate", "inicio_ms": i * 60_000, "emitido_ms": i * 60_000 + 500,
             "sin_motorizado": c} for i, c in enumerate(colas)]


def test_alerta_con_histeresis():
    regla = Regla(umbral_sin_motorizado=7, minutos_para_abrir=2, minutos_para_cerrar=3)
    # un minuto suelto sobre el umbral no abre; dos seguidos sí
    alertas = evaluar_serie(_fotos([8, 2, 9, 10, 3, 12, 2, 1, 0]), regla)
    assert [a["accion"] for a in alertas] == ["abrir", "cerrar"]
    assert alertas[0]["detectado_ms"] == 3 * 60_000 + 500
    # el 12 del minuto 5 no reabre: la alerta seguía abierta
    assert alertas[1]["pico"] == 12
    assert alertas[1]["abierta_ms"] == alertas[0]["detectado_ms"]


def test_evaluar_minuto_sin_cambio_devuelve_none():
    estado = estado_inicial()
    assert evaluar_minuto(estado, _fotos([1])[0], Regla(), 0) is None
    assert estado["racha_buena"] == 1
