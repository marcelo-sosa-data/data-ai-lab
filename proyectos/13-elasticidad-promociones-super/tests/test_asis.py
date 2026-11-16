import numpy as np
import pandas as pd

from elasticidad import asis


def test_base_de_cuatro_semanas_cuadra_con_pandas(con):
    est = asis.estimar(con).dropna(subset=["base_4s"])
    r = est.iloc[5]
    v = con.execute("SELECT semana, SUM(unidades) u FROM ventas_semana WHERE id_sku = ? GROUP BY 1",
                    [r.id_sku]).df()
    v["semana"] = pd.to_datetime(v.semana)
    ini = pd.Timestamp(r.inicio)
    esperado = v[(v.semana >= ini - pd.Timedelta(days=28)) & (v.semana < ini)].u.mean()
    assert np.isclose(r.base_4s, esperado)


def test_alza_se_toma_de_la_promocion_anterior_del_producto(con):
    est = asis.estimar(con)
    con_ant = est.dropna(subset=["alza_anterior"])
    r = con_ant.iloc[0]
    previa = est[(est.id_sku == r.id_sku) & (est.inicio < r.inicio)].iloc[-1]
    assert np.isclose(r.alza_anterior, previa.alza_observada)
    assert np.isclose(r.alza_estimada, previa.alza_observada * r.descuento / previa.descuento)


def test_sin_semanas_previas_no_hay_base(con):
    est = asis.estimar(con)
    con_previas = pd.to_datetime(est.inicio) > pd.Timestamp("2024-11-04")
    assert est.base_4s[~con_previas].isna().all()
    assert est.base_4s[con_previas].notna().all()
    assert est.margen_incremental_asis.notna().sum() > 0.9 * len(est)
