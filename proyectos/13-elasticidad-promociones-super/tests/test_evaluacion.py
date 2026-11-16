import pandas as pd

from elasticidad import evaluacion as E
from elasticidad.simulador import Simulador


def test_resumen_con_casos_armados():
    ev = pd.DataFrame(dict(
        asis_margen=[100.0, 50.0, -10.0], tobe_margen=[-20.0, 40.0, -5.0], real_margen=[-30.0, 60.0, -8.0],
        asis_unid=[10.0, 10.0, 10.0], tobe_unid=[5.0, 8.0, 4.0], real_unid=[5.0, 10.0, 5.0],
        asis_aprueba=[True] * 3, tobe_aprueba=[False, True, False], real_margen_rec=[0.0, 70.0, 0.0],
        real_venta=[100.0, 200.0, 50.0],
    ))
    r = E.resumen(ev).set_index("indicador")
    assert r.loc["aprobadas que perdieron margen", "asis"] == 2
    assert r.loc["aprobadas que perdieron margen", "tobe"] == 0
    assert r.loc["margen incremental real de lo aprobado (S/)", "asis"] == 22
    assert r.loc["margen incremental real de lo aprobado (S/)", "tobe"] == 60
    assert r.loc["aciertos en el signo del margen", "tobe"] == 1


def test_evaluar_promos_de_la_base(con, m, ajuste):
    post, meta, _ = ajuste
    ev = E.evaluar_promos(con, m, Simulador(post, meta, m, n_draws=60), pd.Timestamp("2026-08-01"))
    assert len(ev) > 0 and ev.inicio.min() >= pd.Timestamp("2026-08-01")
    assert ev.tobe_prob.between(0, 1).all()
    # el modelo se acerca más al margen real que la planilla
    err_tobe = (ev.tobe_margen - ev.real_margen).abs().mean()
    err_asis = (ev.asis_margen - ev.real_margen).abs().mean()
    assert err_tobe < err_asis
