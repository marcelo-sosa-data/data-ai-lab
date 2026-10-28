import numpy as np

from demanda import backtest as bt_mod
from demanda.resultados import cargar_backtest, guardar_backtest


def test_ida_y_vuelta(tmp_path, backtest):
    vig = bt_mod.calibradores_vigentes(backtest)
    ruta = tmp_path / "r.duckdb"
    guardar_backtest(ruta, backtest, vig)
    bt2, vig2 = cargar_backtest(ruta)
    assert bt2.cortes == backtest.cortes
    assert len(bt2.predicciones) == len(backtest.predicciones)
    c = backtest.cortes[-1]
    assert bt2.calibradores_suma[c].cuantiles == backtest.calibradores_suma[c].cuantiles
    np.testing.assert_allclose(vig2[0].aplicar([3.0], ["media"], 0.9), vig[0].aplicar([3.0], ["media"], 0.9))
