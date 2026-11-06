import numpy as np

from desercion import explicacion as ex
from desercion import modelos as mo


def test_shap_suma_el_log_odds(pnl):
    tr = pnl[pnl.deserta.notna()].sample(15_000, random_state=1)
    m = mo.entrenar_lgbm(tr, rondas=40)
    x = tr.head(300)
    sv, base = ex.valores_shap(m, x)
    p = mo.predecir(m, x)
    np.testing.assert_allclose(base + sv.sum(axis=1), np.log(p / (1 - p)), atol=1e-6)
    imp = ex.importancia_global(sv)
    assert imp.shap_medio.is_monotonic_decreasing
    razones = ex.razones(x, sv)
    assert all(len(r) <= 3 for r in razones)


def test_textos():
    assert ex.describir("nota_pc1", float("nan"), semana=6) == "no rindió la PC1"
    assert ex.describir("nota_parcial", float("nan"), semana=6) == "aún sin nota de parcial"
    assert ex.describir("nota_parcial", 8.25, semana=9) == "8.2 en la parcial" or \
        ex.describir("nota_parcial", 8.25, semana=9).endswith("en la parcial")
    assert ex.describir("cuotas_vencidas", 2, 9) == "2 cuota(s) vencida(s)"
    assert ex.describir("asistencia_ult2", 0.4, 9) == "asistió al 40% en las dos últimas semanas"
    assert ex.describir("ciclo", 1, 9) == "primer ciclo"
