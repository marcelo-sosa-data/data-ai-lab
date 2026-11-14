from datetime import datetime

import pandas as pd

from pedidos_rt.evaluacion import emparejar, resumir


def _ms(ts):
    return int(pd.Timestamp(ts).value // 1_000_000)


def test_emparejar_incidentes_y_falsas():
    inc = pd.DataFrame([
        {"incidente": "I01", "zona": "Surco", "inicio": datetime(2026, 10, 5, 19, 0),
         "fin": datetime(2026, 10, 5, 19, 30), "causa": "x"},
        {"incidente": "I02", "zona": "Ate", "inicio": datetime(2026, 10, 5, 20, 0),
         "fin": datetime(2026, 10, 5, 20, 30), "causa": "y"},
    ])
    alertas = pd.DataFrame([
        {"zona": "Surco", "accion": "abrir", "detectado_ms": _ms("2026-10-05 19:12")},
        {"zona": "Surco", "accion": "cerrar", "detectado_ms": _ms("2026-10-05 19:40")},
        {"zona": "Surco", "accion": "abrir", "detectado_ms": _ms("2026-10-05 19:45")},   # reapertura
        {"zona": "Ate", "accion": "abrir", "detectado_ms": _ms("2026-10-05 18:00")},     # antes: falsa
        {"zona": "Ate", "accion": "abrir", "detectado_ms": _ms("2026-10-05 21:30")},     # fuera: falsa
    ])
    pedidos = pd.DataFrame({
        "pedido_id": ["A", "B", "C", "D"],
        "zona": ["Surco", "Surco", "Surco", "Ate"],
        "ev_creado": pd.to_datetime(["2026-10-05 19:05", "2026-10-05 19:11", "2026-10-05 19:20",
                                     "2026-10-05 20:10"]),
        "cancelado": [True, False, False, True],
    })
    det, falsas = emparejar(alertas, inc, pedidos)
    assert falsas == 2
    surco = det.set_index("incidente").loc["I01"]
    assert surco["demora_min"] == 12
    assert surco["pedidos_antes_alerta"] == 2 and surco["cancelados_antes_alerta"] == 1
    ate = det.set_index("incidente").loc["I02"]
    assert pd.isna(ate["detectado"]) and ate["pedidos_antes_alerta"] == 1

    r = resumir("x", det, falsas, dias=1)
    assert r["detectados"] == 1 and r["demora_mediana_min"] == 12.0 and r["falsas_por_dia"] == 2
