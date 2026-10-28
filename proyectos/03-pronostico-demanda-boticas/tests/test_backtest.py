import numpy as np
import pandas as pd

from demanda import backtest as bt_mod
from demanda.metricas import wape


def test_cortes_son_lunes_y_dejan_14_dias(base):
    cortes = bt_mod.cortes_por_defecto(base, n=5)
    assert all(c.dayofweek == 0 for c in cortes)
    assert cortes[-1] + pd.Timedelta(days=14) <= base.ultimo_dia
    assert np.diff(cortes).astype("timedelta64[D]").astype(int).tolist() == [14] * 4


def test_predicciones_solo_despues_del_corte(backtest):
    p = backtest.predicciones
    assert (p.fecha > p.corte).all()
    assert p.horizonte.between(1, bt_mod.DIAS_PREDICCION).all()
    for m in bt_mod.MODELOS:
        assert p[m].notna().all() and (p[m] >= 0).all()


def test_lightgbm_le_gana_a_los_baselines(backtest):
    ev = backtest.predicciones.query("horizonte <= 14 and not quiebre")
    assert wape(ev.unidades, ev.lgbm) < wape(ev.unidades, ev.naive_estacional)
    assert wape(ev.unidades, ev.lgbm) < wape(ev.unidades, ev.promedio_28)


def test_intervalos_calibrados_solo_con_cortes_anteriores(backtest):
    p = backtest.predicciones
    primero = backtest.cortes[0]
    assert p.loc[p.corte == primero, "lgbm_p10"].isna().all()
    assert set(backtest.calibradores) == set(backtest.cortes[1:])
    resto = p[p.corte != primero]
    assert (resto.lgbm_p10 <= resto.lgbm_p90).all()


def test_tablas_de_resumen(backtest, base):
    t = bt_mod.tabla_modelos(backtest.predicciones, base.latente)
    assert list(t.modelo) == bt_mod.MODELOS
    assert t.wape.between(0, 2).all()
    c = bt_mod.tabla_cobertura(backtest.predicciones)
    assert c.loc[c.segmento == "total", "cobertura"].iloc[0] > 0.6


def test_ventana_de_pedido_segun_lead_time(backtest):
    s = bt_mod.sumas_por_ventana(backtest.predicciones)
    lima = s.merge(backtest.predicciones[["id_local", "region"]].drop_duplicates(), on="id_local")
    assert set(lima.loc[lima.region == "Lima", "dias"]) == {8}
    assert set(lima.loc[lima.region != "Lima", "dias"]) == {10}
