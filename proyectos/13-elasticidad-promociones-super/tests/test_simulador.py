import numpy as np
import pandas as pd
import pytest

from elasticidad.simulador import Escenario, Simulador


@pytest.fixture(scope="module")
def sim(ajuste, m):
    post, meta, _ = ajuste
    return Simulador(post, meta, m, n_draws=100)


def esc(**kw):
    base = dict(id_sku="501", inicio=pd.Timestamp("2026-11-16"), semanas=1, descuento=0.2,
                encarte=True, aporte_pct=0.0)
    base.update(kw)
    return Escenario(**base)


def test_sin_descuento_no_hay_incremental(sim):
    s = sim.simular(esc(descuento=0.0))
    assert np.allclose(s["margen_incremental"], 0) and np.allclose(s["unid_propias"], 0)


def test_promocion_canibaliza_y_suma_unidades(sim):
    s = sim.simular(esc())
    assert (s["unid_propias"] > 0).all()
    assert (s["unid_canibalizadas"] < 0).all()


def test_el_aporte_del_proveedor_mejora_el_margen(sim):
    a = sim.resumir(esc(aporte_pct=0.0))["margen_media"]
    b = sim.resumir(esc(aporte_pct=0.8))["margen_media"]
    assert b > a


def test_detergente_cae_despues_de_la_promocion(sim):
    s = sim.resumir(esc(id_sku="301", inicio=pd.Timestamp("2026-11-09")))
    assert s["unid_post"] < 0


def test_semana_fuera_del_calendario(sim):
    with pytest.raises(ValueError):
        sim.simular(esc(inicio=pd.Timestamp("2030-01-07")))


def test_recomendacion_respeta_la_probabilidad(sim):
    rec = sim.recomendar(esc(id_sku="201", aporte_pct=0.0))
    assert rec["descuento"] == 0 or rec["prob_gana"] >= 0.6
    assert set(rec["curva"].descuento) == {0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35}
