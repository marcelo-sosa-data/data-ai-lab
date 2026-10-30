import numpy as np

from experimentos.asignacion import asignar, cubeta


def test_es_deterministica():
    ids = np.arange(1, 5001)
    assert (asignar(ids, "exp-01") == asignar(ids, "exp-01")).all()
    assert cubeta(123, "exp-01") == cubeta(123, "exp-01")


def test_reparto_cerca_del_esperado():
    ids = np.arange(1, 40_001)
    for reparto in (0.5, 0.2):
        frac = asignar(ids, "exp-xx", reparto).mean()
        # 4 errores estándar de una binomial
        assert abs(frac - reparto) < 4 * np.sqrt(reparto * (1 - reparto) / len(ids))


def test_sales_distintas_son_independientes():
    ids = np.arange(1, 40_001)
    a, b = asignar(ids, "exp-01"), asignar(ids, "exp-02")
    # si fueran la misma asignación coincidirían 100%; independientes, ~50%
    assert abs((a == b).mean() - 0.5) < 0.02
