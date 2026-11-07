import numpy as np
import pandas as pd
import pytest

from cohortes.ltv import SEGMENTOS, descontar, mes_payback, segmentar
from cohortes.modelos import ModeloCompras, ModeloGasto, columnas_canal, tasa_historica


def simular_bgnbd(n, r, alpha, a, b, T, holdout, rng):
    """Clientes que siguen un BG/NBD de verdad: compras hasta T y en los `holdout` días siguientes."""
    lam = rng.gamma(r, 1 / alpha, n)
    p = rng.beta(a, b, n)
    filas = []
    for i in range(n):
        t, ult, x, fut, vivo = 0.0, 0.0, 0, 0, True
        while vivo:
            t += rng.exponential(1 / lam[i])
            if t > T + holdout:
                break
            if t <= T:
                x, ult = x + 1, t
            else:
                fut += 1
            vivo = rng.random() > p[i]
        filas.append((i, x, ult, T, fut))
    return pd.DataFrame(filas, columns=["customer_id", "frequency", "recency", "T", "futuro"]).astype(
        {"frequency": float, "recency": float, "T": float})


@pytest.fixture(scope="module")
def simulados():
    rng = np.random.default_rng(5)
    a = simular_bgnbd(2500, 1.2, 8.0, 0.4, 4.0, 200, 120, rng).assign(canal="Orgánico")
    b = simular_bgnbd(2500, 1.2, 20.0, 1.2, 3.0, 200, 120, rng).assign(canal="TikTok Ads")
    b["customer_id"] += len(a)
    return pd.concat([a, b], ignore_index=True)


def test_bgnbd_con_canal_predice_el_futuro_simulado(simulados):
    m = ModeloCompras(["Orgánico", "TikTok Ads"]).ajustar(simulados)
    pred = m.compras_esperadas(simulados, 120)
    for canal, d in simulados.assign(pred=pred).groupby("canal"):
        assert d.pred.sum() == pytest.approx(d.futuro.sum(), rel=0.10), canal
    p = m.parametros().set_index("parametro").valor
    # alpha = alpha_scale * exp(-coef): TikTok compra menos seguido, así que su coeficiente es negativo
    assert p["purchase_coefficient_alpha[canal_tiktok_ads]"] < 0


def test_el_ritmo_historico_sobreestima(simulados):
    assert tasa_historica(simulados, 120).sum() > 1.2 * simulados.futuro.sum()


def test_mbg_no_da_por_vivo_a_quien_compro_una_vez(simulados):
    viejo = simulados[(simulados.frequency == 0)].head(50)
    bg = ModeloCompras(["Orgánico", "TikTok Ads"]).ajustar(simulados)
    mbg = ModeloCompras(["Orgánico", "TikTok Ads"], modificado=True).ajustar(simulados)
    assert np.allclose(bg.prob_vivo(viejo), 1.0)
    assert mbg.prob_vivo(viejo).max() < 0.9


def test_nuevo_cliente_crece_con_el_tiempo(simulados):
    m = ModeloCompras(["Orgánico", "TikTok Ads"]).ajustar(simulados)
    nc = m.nuevo_cliente([30, 180, 365])
    for _, d in nc.groupby("canal"):
        assert d.sort_values("dias").compras.is_monotonic_increasing
    o, t = nc[nc.dias == 365].set_index("canal").compras[["Orgánico", "TikTok Ads"]]
    assert o > t


def test_gamma_gamma_por_canal():
    rng = np.random.default_rng(1)
    n = 1500
    df = pd.DataFrame({"customer_id": np.arange(2 * n), "canal": ["A"] * n + ["B"] * n,
                       "frequency": rng.integers(1, 30, 2 * n).astype(float)})
    media = np.r_[rng.gamma(6, 0.5 / 6, n), rng.gamma(6, 1.5 / 6, n)]
    df["monetary_value"] = rng.gamma(df.frequency * 4, media / (df.frequency * 4))
    g = ModeloGasto().ajustar(df)
    nuevo = g.gasto_nuevo()
    assert nuevo["A"] == pytest.approx(0.5, rel=0.15) and nuevo["B"] == pytest.approx(1.5, rel=0.15)
    sin_historia = df.head(1).assign(frequency=0.0, monetary_value=0.0)
    assert g.gasto_esperado(sin_historia)[0] == pytest.approx(nuevo["A"], rel=1e-6)


def test_columnas_canal_sin_tildes_ni_base():
    c = columnas_canal(["Orgánico", "Agentes en tienda", "Google Search"])
    assert c == {"Agentes en tienda": "canal_agentes_en_tienda", "Google Search": "canal_google_search"}


def test_descuento_y_payback():
    vp = descontar(np.full(12, 10.0), 0.01)
    assert vp[0] == pytest.approx(10 / 1.01) and vp[-1] < 120
    curva = pd.Series([5.0, 9.0, 12.0, 14.0], index=[1, 2, 3, 4])
    assert mes_payback(curva, 10) == 3
    assert np.isnan(mes_payback(curva, 20))


def test_segmentos():
    df = pd.DataFrame({"ingreso_historico": [100, 90, 1, 1, 1, 1, 1, 1, 1, 1],
                       "p_vivo": [0.99, 0.5, 0.95, 0.5, 0.01, 0.5, 0.5, 0.5, 0.5, 0.5]})
    s = segmentar(df)
    assert list(s[:5]) == ["Valiosos activos", "Valiosos en riesgo", "Activos", "En duda", "Probablemente perdidos"]
    assert set(s) <= set(SEGMENTOS)
