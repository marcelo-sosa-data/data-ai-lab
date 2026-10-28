import numpy as np
import pytest

from demanda import reposicion as rep


@pytest.fixture(scope="module")
def sims(base, backtest):
    return {p: rep.simular(base, backtest, p) for p in rep.POLITICAS}


def test_regla_actual_reproduce_la_historia(base, sims):
    """La historia se generó con esa regla: el simulador tiene que dar exactamente lo mismo."""
    d = sims["regla_actual"].diario.merge(base.ventas, on=["fecha", "id_local", "id_producto"])
    assert len(d) == len(sims["regla_actual"].diario)
    assert (d.venta == d.unidades).all()
    assert (d.stock_cierre_x == d.stock_cierre_y).all()


def test_invariantes(sims):
    for s in sims.values():
        assert (s.diario.stock_cierre >= 0).all()
        assert (s.diario.venta <= s.diario.demanda).all()


def test_el_margen_sube_el_nivel_de_servicio(base, sims):
    ind = {p: rep.indicadores(s, base).iloc[0] for p, s in sims.items()}
    assert ind["pronostico_p90"].nivel_servicio > ind["pronostico"].nivel_servicio
    assert ind["pronostico_p90"].inventario_promedio > ind["pronostico"].inventario_promedio


def test_pronostico_perfecto_casi_no_quiebra(base, backtest):
    """Con la demanda real como pronóstico, el único quiebre posible es el redondeo."""
    perfecto = backtest
    p = perfecto.predicciones.merge(base.latente, on=["fecha", "id_local", "id_producto"], how="left")
    original = perfecto.predicciones.lgbm.copy()
    perfecto.predicciones["lgbm"] = p.demanda.fillna(0).to_numpy()
    try:
        s = rep.simular(base, perfecto, "pronostico")
        assert rep.indicadores(s, base).iloc[0].nivel_servicio > 0.995
    finally:
        perfecto.predicciones["lgbm"] = original.to_numpy()


def test_politica_desconocida(base, backtest):
    with pytest.raises(ValueError):
        rep.simular(base, backtest, "a_ojo")


def test_indicadores_por_categoria(base, sims):
    t = rep.indicadores(sims["pronostico_p90"], base, por="categoria")
    assert set(t.categoria) == set(base.productos.categoria)
    assert np.isfinite(t.dias_de_inventario).all()
