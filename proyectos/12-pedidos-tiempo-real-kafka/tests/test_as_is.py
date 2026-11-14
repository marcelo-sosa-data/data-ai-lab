from datetime import datetime, timedelta

import pandas as pd
import pytest

from pedidos_rt import as_is
from pedidos_rt.config import Regla

D = datetime(2026, 10, 5)


def _t(h, m, s=0):
    return D + timedelta(hours=h, minutes=m, seconds=s)


@pytest.fixture
def con(tmp_path):
    filas = [
        # P1: asignado tarde (espera 8 min) y con reintento
        ("E1", "P1", "creado", _t(10, 1), _t(10, 1, 1), None, False),
        ("E2", "P1", "asignado", _t(10, 9), _t(10, 9, 1), 480.0, False),
        ("E2", "P1", "asignado", _t(10, 9), _t(10, 9, 9), 480.0, True),
        # P2: asignado a los 2 min, pero el evento llega a las 10:20
        ("E3", "P2", "creado", _t(10, 2), _t(10, 2, 1), None, False),
        ("E4", "P2", "asignado", _t(10, 4), _t(10, 20), 120.0, False),
    ]
    for i in range(3, 10):     # siete pedidos de 10:05 a 10:11 que nadie toma
        filas.append((f"E{i + 10}", f"P{i}", "creado", _t(10, i + 2), _t(10, i + 2, 1), None, False))
    df = pd.DataFrame(filas, columns=["evento_id", "pedido_id", "tipo", "ts_evento", "ts_recibido",
                                      "espera_asignacion_s", "es_reintento"])
    df["zona"] = "Ate"
    df["app"] = "cliente"
    ruta = tmp_path / "eventos.parquet"
    df.to_parquet(ruta, index=False)
    return as_is.conectar(ruta)


def test_tablero_cuenta_reintentos_y_pierde_tardios(con):
    tab = as_is.tablero_demoradas(con, Regla(minimo_asignaciones=1), cada_min=15)
    b = tab[tab["corte"] == _t(10, 15)].iloc[0]
    assert b["creados"] == 9
    assert b["asignados"] == 2           # P1 dos veces; P2 llegó después del refresco
    assert b["demoradas"] == 2
    assert bool(b["en_rojo"])
    assert tab[tab["corte"] == _t(10, 30)].iloc[0]["asignados"] == 0   # P2 no vuelve a su bloque


def test_cola_con_y_sin_llegada(con):
    regla = Regla()
    con_lleg = as_is.cola_por_corte(con, regla, 15, con_llegada=True)
    real = as_is.cola_por_corte(con, regla, 15, con_llegada=False)
    corte = _t(10, 15)
    # a las 10:15 el log todavía no tiene la asignación de P2: parece pendiente
    assert con_lleg.loc[con_lleg["corte"] == corte, "sin_motorizado"].item() == 8
    assert real.loc[real["corte"] == corte, "sin_motorizado"].item() == 7


def test_alertas_batch_y_cifras(con):
    regla = Regla()
    cola = as_is.cola_por_corte(con, regla, 15, con_llegada=True)
    al = as_is.alertas_de_serie(cola, None, regla, por_evaluacion=True)
    assert al.iloc[0]["accion"] == "abrir"
    assert pd.Timestamp(al.iloc[0]["detectado_ms"], unit="ms") == _t(10, 15)
    cif = as_is.cifras_tablero(con, 15)
    assert cif["asignado"] == {"verdad": 2, "mostrado": 2, "reintentos": 1, "no_llegaron": 1}
