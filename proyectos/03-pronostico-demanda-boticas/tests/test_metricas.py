import numpy as np
import pytest

from demanda.metricas import cobertura, sesgo, wape


def test_wape_y_sesgo():
    real = [10, 0, 5, 5]
    pred = [8, 1, 5, 7]
    assert wape(real, pred) == pytest.approx(5 / 20)
    assert sesgo(real, pred) == pytest.approx(1 / 20)


def test_wape_sin_venta_es_nan():
    assert np.isnan(wape([0, 0], [1, 2]))


def test_cobertura_incluye_los_bordes():
    assert cobertura([1, 2, 3, 4], [1, 0, 0, 5], [1, 3, 2, 9]) == 0.5
