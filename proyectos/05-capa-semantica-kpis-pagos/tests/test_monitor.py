import numpy as np
import pandas as pd
import pytest

from kpis.calendario import es_dia_de_pago
from kpis.monitor import Configuracion, eventos, evaluar, vigilar, vigilar_serie


def _serie(seed=0, dias=300):
    rng = np.random.default_rng(seed)
    f = pd.date_range("2025-01-01", periods=dias, freq="D")
    dow = np.array([0.9, 0.9, 0.95, 1.0, 1.15, 1.3, 1.0])[f.dayofweek]
    pago = np.where(es_dia_de_pago(f), 1.12, 1.0)
    nivel = 5000 * np.exp(0.0006 * np.arange(dias))
    return pd.Series(nivel * dow * pago * rng.lognormal(0, 0.02, dias), index=f)


def test_serie_con_estacionalidad_conocida_no_alerta():
    r = vigilar_serie(_serie(), multiplicativo=True, umbral=0.08)
    assert r.alerta.sum() == 0
    assert r.z.abs().median() < 1.2


def test_detecta_una_caida_y_no_se_contamina():
    s = _serie(1)
    s.iloc[200] *= 0.85
    r = vigilar_serie(s, multiplicativo=True, umbral=0.08).set_index("fecha")
    assert r.loc[s.index[200], "alerta"]
    assert r.loc[s.index[200], "desvio"] == pytest.approx(-0.15, abs=0.04)
    assert r.alerta.sum() == 1  # los días siguientes no heredan la caída


def test_umbral_de_negocio_filtra_alertas_chicas():
    s = _serie(2)
    s.iloc[200] *= 0.89  # z alto, pero 11% no llega a un umbral de 15%
    assert vigilar_serie(s, multiplicativo=True, umbral=0.15).alerta.sum() == 0
    assert vigilar_serie(s, multiplicativo=True, umbral=0.08).alerta.sum() == 1


def test_tasas_en_nivel_y_dias_previos_al_pago():
    rng = np.random.default_rng(3)
    f = pd.date_range("2025-01-01", periods=250, freq="D")
    previo = ((f.day >= 10) & (f.day <= 14)) | ((f.day >= 25) & (f.day <= 29))
    s = pd.Series(0.94 - 0.01 * previo + rng.normal(0, 0.002, len(f)), index=f)
    con = vigilar_serie(s, False, 0.006, Configuracion(previo_pago=True))
    sin = vigilar_serie(s, False, 0.006, Configuracion(previo_pago=False))
    assert con.z.abs().median() < sin.z.abs().median()


def test_eventos_agrupa_dias_seguidos():
    f = pd.date_range("2026-01-01", periods=10)
    s = pd.DataFrame({"fecha": f, "metrica": "m", "z": np.arange(10.0), "desvio": 0.1,
                      "alerta": [0, 1, 1, 0, 1, 0, 0, 0, 0, 1]}).astype({"alerta": bool})
    ev = eventos(s)
    assert list(ev.dias) == [3, 1]
    assert ev.peor_dia.iloc[0] == f[4]


def test_detecta_los_incidentes_del_generador(capa, con):
    serie = vigilar(capa, con)
    ev, falsas = evaluar(serie, con.execute("SELECT * FROM incidentes").df())
    # los tres incidentes de aprobación salen aun con un cuarto del volumen; la carga que faltó
    # (-12% de un día) se ve a escala completa pero aquí queda dentro del ruido
    assert ev.set_index("id_incidente").loc[["INC-1", "INC-3", "INC-4"], "detectado"].all(), ev
    assert len(falsas) / len(serie) < 0.03
