import pandas as pd
import pytest

from desercion import supervivencia as sv
from desercion.datos import desenlaces
from desercion.features import estaticas


def test_riesgo_semanal_a_mano():
    t = pd.DataFrame({"duracion": [3, 3, 17, 17, 17], "evento": [1, 0, 1, 0, 0]})
    h = sv.riesgo_semanal(t).set_index("semana")
    assert h.loc[3, "en_riesgo"] == 5 and h.loc[3, "abandonos"] == 1
    assert h.loc[17, "en_riesgo"] == 3 and h.loc[17, "riesgo"] == pytest.approx(1 / 3)


def test_kaplan_meier_y_cox(base, pnl):
    t = sv.tabla(estaticas(base), desenlaces(base))
    assert t.evento.sum() > 0 and t.periodo.ne(base.periodo_actual).all()
    km, p = sv.kaplan_meier(t, "ciclo")
    fin = km.groupby("valor").permanencia.last()
    assert fin["1-2"] < fin["5 a 10"] and p < 0.01
    # sin censura intermedia, la permanencia final de KM es 1 - tasa de deserción
    assert km[km.valor == "5 a 10"].permanencia.iloc[-1] == pytest.approx(
        1 - t[t.ciclo >= 5].evento.mean(), abs=1e-9)
    cox = sv.cox_landmark(pnl[pnl.semana == 4], semana=4)
    hr = cox.set_index("variable").hr
    assert hr["asistencia_bajo_80"] > 1.5 and hr["primer_año"] > 1
