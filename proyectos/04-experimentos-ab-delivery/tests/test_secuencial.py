import numpy as np
from scipy import stats

from experimentos.secuencial import lambda_msprt, semiancho_msprt


def test_semiancho_es_la_frontera_de_rechazo():
    var, tau2 = 0.004, 0.01
    h = semiancho_msprt(var, tau2)
    assert np.isclose(lambda_msprt(h, var, tau2), 20.0)
    assert lambda_msprt(0.9 * h, var, tau2) < 20 < lambda_msprt(1.1 * h, var, tau2)


def test_mirar_cada_dia_infla_el_error_y_msprt_no():
    rng = np.random.default_rng(5)
    reps, looks, por_look = 2000, 20, 200
    n = por_look * np.arange(1, looks + 1)
    # medias acumuladas de dos grupos sin diferencia, vistas en 20 momentos
    ma = rng.normal(0, 1, (reps, looks * por_look)).cumsum(1)[:, n - 1] / n
    mb = rng.normal(0, 1, (reps, looks * por_look)).cumsum(1)[:, n - 1] / n
    dif, var = ma - mb, 2 / n
    clasico = (np.abs(dif / np.sqrt(var)) > stats.norm.ppf(0.975)).any(1).mean()
    msprt = (lambda_msprt(dif, np.broadcast_to(var, dif.shape), 0.05**2) >= 20).any(1).mean()
    assert clasico > 0.15
    assert msprt < 0.05
