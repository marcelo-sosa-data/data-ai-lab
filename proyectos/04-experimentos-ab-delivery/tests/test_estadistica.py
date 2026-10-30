import numpy as np
from scipy import stats

from experimentos.estadistica import (benjamini_hochberg, comparar_medias, comparar_ratio, cuped, mde_relativo,
                                      n_necesario, srm)


def test_welch_coincide_con_scipy():
    rng = np.random.default_rng(1)
    y = np.concatenate([rng.gamma(1.2, 1.5, 4000), rng.gamma(1.2, 1.6, 4000)])
    t = np.r_[np.zeros(4000, bool), np.ones(4000, bool)]
    c = comparar_medias(y, t)
    ref = stats.ttest_ind(y[t], y[~t], equal_var=False)
    assert abs(c.p_valor - ref.pvalue) < 0.002
    assert np.isclose(c.diferencia, y[t].mean() - y[~t].mean())


def test_cuped_es_insesgado_y_reduce_varianza():
    rng = np.random.default_rng(2)
    efectos, ee_raw, ee_cuped = [], [], []
    for _ in range(300):
        n = 4000
        x = rng.gamma(1.0, 2.0, n)
        t = rng.random(n) < 0.5
        y = 0.8 * x + rng.normal(0, 1.5, n) + 0.10 * t
        c = cuped(y, x, t)
        efectos.append(c.diferencia)
        ee_cuped.append(c.error_estandar)
        ee_raw.append(comparar_medias(y, t).error_estandar)
    assert abs(np.mean(efectos) - 0.10) < 0.01
    rho2 = 0.8**2 * 4 / (0.8**2 * 4 + 1.5**2)
    assert abs(1 - (np.mean(ee_cuped) / np.mean(ee_raw)) ** 2 - rho2) < 0.03
    assert abs(c.reduccion_varianza - rho2) < 0.05


def test_metodo_delta_contra_bootstrap():
    rng = np.random.default_rng(3)
    n = 3000
    pedidos = rng.poisson(1.6, 2 * n)
    gmv = np.array([rng.lognormal(3.5, 0.4, k).sum() for k in pedidos])
    t = np.r_[np.zeros(n, bool), np.ones(n, bool)]
    c = comparar_ratio(gmv, pedidos, t)
    boot = []
    for _ in range(400):
        i0, i1 = rng.integers(0, n, n), rng.integers(n, 2 * n, n)
        boot.append(gmv[i1].sum() / pedidos[i1].sum() - gmv[i0].sum() / pedidos[i0].sum())
    assert abs(c.error_estandar / np.std(boot) - 1) < 0.12


def test_srm():
    assert srm(30_000, 30_050) > 0.5
    assert srm(31_226, 29_505) < 1e-6
    assert srm(8_000, 2_000, reparto_tratamiento=0.2) > 0.5


def test_benjamini_hochberg():
    p = np.array([0.01, 0.04, 0.03, 0.50])
    # ordenados: 0.01*4/1, 0.03*4/2, 0.04*4/3, 0.5 -> con monotonía: 0.04, 0.0533, 0.0533, 0.5
    assert np.allclose(benjamini_hochberg(p), [0.04, 0.05333, 0.05333, 0.5], atol=1e-4)


def test_mde_y_tamano_son_inversos():
    n = n_necesario(media=1.6, sd=2.1, mde=0.03, rho=0.55)
    assert abs(mde_relativo(1.6, 2.1, n, rho=0.55) - 0.03) < 1e-3
    assert n_necesario(1.6, 2.1, 0.03, rho=0.55) < n_necesario(1.6, 2.1, 0.03)
