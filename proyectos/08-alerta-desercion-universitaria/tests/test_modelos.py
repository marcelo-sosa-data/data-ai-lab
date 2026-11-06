import numpy as np
import pandas as pd

from desercion import modelos as mo


def test_regla_actual():
    df = pd.DataFrame({
        "asistencia_acum": [0.65, 0.90, 0.90, 0.90, 0.95],
        "nota_pc1": [12, 9.5, 12, 12, np.nan],
        "nota_parcial": [np.nan, 11, 12, 12, np.nan],
        "nota_pc2": [np.nan] * 5,
        "cuotas_vencidas": [0, 0, 2, 1, 0],
    })
    assert mo.regla_actual(df).tolist() == [True, True, True, False, False]
    orden = mo.orden_regla(df)
    assert orden.iloc[0] > orden.iloc[3]


def test_calibrador_monotono():
    rng = np.random.default_rng(0)
    p = rng.random(5000)
    y = rng.random(5000) < p ** 2          # el modelo sobreestima
    cal = mo.Calibrador().ajustar(p, y)
    q = cal(np.linspace(0, 1, 50))
    assert (np.diff(q) >= 0).all() and q.min() >= 0 and q.max() <= 1
    assert cal(np.array([0.5]))[0] < 0.4


def test_modelos_entrenan(pnl):
    tr = pnl[pnl.deserta.notna()].sample(20_000, random_state=0)
    m = mo.entrenar_lgbm(tr, rondas=30)
    lr = mo.entrenar_logistica(tr)
    for modelo in (m, lr):
        p = mo.predecir(modelo, tr.head(500))
        assert p.shape == (500,) and ((p >= 0) & (p <= 1)).all()
