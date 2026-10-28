import numpy as np

from demanda.intervalos import Calibrador
from demanda.metricas import cobertura


def _datos(rng, n):
    mu = rng.choice([0.5, 3.0, 20.0], size=n)
    seg = np.where(mu < 1, "baja", np.where(mu < 5, "media", "alta"))
    return rng.poisson(mu), mu, seg


def test_cobertura_cercana_a_la_nominal_fuera_de_muestra():
    rng = np.random.default_rng(0)
    y_cal, mu_cal, seg_cal = _datos(rng, 20_000)
    y, mu, seg = _datos(rng, 20_000)
    c = Calibrador.ajustar(y_cal, mu_cal, seg_cal)
    lo, hi = c.aplicar(mu, seg, 0.1), c.aplicar(mu, seg, 0.9)
    # con conteos el intervalo incluye los bordes, así que tiende a cubrir algo más de 80%
    assert 0.78 <= cobertura(y, lo, hi) <= 0.92
    for g in ("baja", "media", "alta"):
        m = seg == g
        assert cobertura(y[m], lo[m], hi[m]) >= 0.75


def test_limites_ordenados_y_no_negativos():
    rng = np.random.default_rng(1)
    y, mu, seg = _datos(rng, 2_000)
    c = Calibrador.ajustar(y, mu, seg)
    lo, hi = c.aplicar(mu, seg, 0.1), c.aplicar(mu, seg, 0.9)
    assert (lo >= 0).all() and (lo <= hi).all()


def test_segmento_con_pocos_datos_usa_el_global():
    rng = np.random.default_rng(2)
    y, mu, seg = _datos(rng, 2_000)
    seg[:10] = "raro"
    c = Calibrador.ajustar(y, mu, seg, min_obs=50)
    assert "raro" not in c.cuantiles
    np.testing.assert_allclose(c.aplicar([4.0], ["raro"], 0.9), c.aplicar([4.0], ["_todos"], 0.9))
