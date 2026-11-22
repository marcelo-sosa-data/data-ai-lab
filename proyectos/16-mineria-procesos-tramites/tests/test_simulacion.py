import numpy as np
import pandas as pd
import pytest

from tramites import catalogos as K
from tramites import simulacion as S
from tramites import tiempos as T
from tramites.calendario import a_calendario, a_habiles


@pytest.fixture(scope="module")
def par(ev_t, log):
    return S.estimar(ev_t, log.tramites, K.INICIO_LOG, K.FIN_PRUEBA)


def test_probabilidades_en_rango(par):
    for k, v in par.p.items():
        assert 0 <= v <= 1, k
    assert 0.2 < par.p["no_pago"] < 0.4
    assert par.firma_dias == (4,) and par.firma_hora == 10.0


def test_ausencias_de_febrero(ev_t, log):
    aus = S.ausencias_direccion(ev_t, log.tramites)
    assert len(aus) > 0
    assert (pd.to_datetime(aus["desde"]).dt.month == 2).all()
    assert (aus["normal_desde"] > aus["hasta"]).all()


def test_reloj_coincide_con_el_calendario(par):
    reloj = S.Reloj(par, pd.Timestamp("2027-02-01"))
    for t in ["2026-03-10 11:15", "2026-08-03 16:40", "2026-10-23 08:05"]:
        h = a_habiles(pd.Timestamp(t))
        dias = reloj.calendario(h)
        assert abs(dias - (pd.Timestamp(t) - pd.Timestamp("2025-12-01")).total_seconds() / 86400) < 1e-3
        assert abs(reloj.habiles(dias) - h) < 0.02


def test_firma_espera_al_siguiente_turno(par):
    import copy
    p = copy.copy(par)
    p.firma_salto = 0.0
    p.firma_demora_h = np.array([0.0])
    rec = S.Recorrido(p, K.Reglas(), True, np.random.default_rng(0), pd.Timestamp("2027-01-31"),
                      S.Reloj(p, pd.Timestamp("2027-01-31")))
    martes = a_habiles(pd.Timestamp("2026-09-08 15:00"))
    assert a_calendario(rec.firma(martes)) == pd.Timestamp("2026-09-11 10:00")


def test_simulacion_del_actual_reproduce_lo_observado(par, log):
    """Estimado y simulado en el mismo periodo, la mediana sale parecida (con la base chica, holgura de 35%)."""
    casos = T.casos(log)
    prueba = log.tramites[log.tramites["registro"].between(K.INICIO_LOG, K.FIN_PRUEBA)]
    sim = S.indicadores(S.simular(par, prueba, K.Reglas(), actual=True, replicas=3))
    obs = S.indicadores(casos[casos["id_tramite"].isin(prueba["id_tramite"])])
    for tipo in (K.CONVALIDACION, K.RETIRO):
        s = sim.set_index("tipo").loc[tipo, "mediana_dias"]
        o = obs.set_index("tipo").loc[tipo, "mediana_dias"]
        assert abs(s / o - 1) < 0.35, tipo


def test_visto_bueno_solo_becados_saca_a_los_retiros_de_direccion(par, log):
    prueba = log.tramites[log.tramites["tipo"] == K.RETIRO]
    a = S.simular(par, prueba, K.ESCENARIOS["actual"][1], actual=True, replicas=2)
    b = S.simular(par, prueba, K.ESCENARIOS["e3"][1], actual=False, replicas=2)
    assert a["direccion"].mean() > 0.9
    becados = prueba["becado"].mean()
    assert abs(b["direccion"].mean() - becados) < 0.05
    assert b["duracion_dias"].median() < a["duracion_dias"].median()
