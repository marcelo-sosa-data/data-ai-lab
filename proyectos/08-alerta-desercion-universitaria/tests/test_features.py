import numpy as np
import pandas as pd
import pytest

from desercion.datos import Base
from desercion.features import COLUMNAS, estaticas, matrices, semana


def _copia(base: Base) -> Base:
    return Base(**{k: (v.copy() if isinstance(v, pd.DataFrame) else v) for k, v in base.__dict__.items()})


@pytest.mark.parametrize("w", [3, 8, 12])
def test_sin_fuga_del_futuro(base, w):
    """Cambiar lo que pasa en 2025-1 después de la semana w no mueve las variables de 2025-1 en la semana w."""
    per = "2025-1"
    antes = semana(matrices(base), estaticas(base), w)
    b = _copia(base)
    b.asistencia.loc[(b.asistencia.periodo == per) & (b.asistencia.semana > w), "asistidas"] = 0
    lv = (b.aula_virtual.periodo == per) & (b.aula_virtual.semana > w)
    b.aula_virtual.loc[lv, ["ingresos", "tareas_entregadas"]] = 0
    b.evaluaciones.loc[(b.evaluaciones.periodo == per) & (b.evaluaciones.semana > w), "nota"] = 0.0
    b.cuotas.loc[(b.cuotas.periodo == per) & (b.cuotas.semana_pago > w), "semana_pago"] = pd.NA
    despues = semana(matrices(b), estaticas(b), w)
    m = (antes.periodo == per).to_numpy()
    assert (despues.periodo == per).sum() == m.sum() > 0
    pd.testing.assert_frame_equal(antes.loc[m, COLUMNAS], despues.loc[m, COLUMNAS])


def test_valores_de_un_alumno(base):
    mx, est = matrices(base), estaticas(base)
    df = semana(mx, est, 8)
    fila = df[df.activo].iloc[0]
    a = base.asistencia[(base.asistencia.id_alumno == fila.id_alumno) & (base.asistencia.periodo == fila.periodo)
                        & (base.asistencia.semana <= 8)]
    assert fila.asistencia_acum == pytest.approx(a.asistidas.sum() / a.sesiones.sum())
    ult = a[a.semana >= 7]
    assert fila.asistencia_ult2 == pytest.approx(ult.asistidas.sum() / ult.sesiones.sum())
    ev = base.evaluaciones.set_index(["id_alumno", "periodo", "evaluacion"]).nota
    np.testing.assert_equal(fila.nota_parcial, ev.get((fila.id_alumno, fila.periodo, "Parcial")))
    cu = base.cuotas[(base.cuotas.id_alumno == fila.id_alumno) & (base.cuotas.periodo == fila.periodo)]
    vencidas = ((cu.semana_vencimiento <= 8) & (cu.semana_pago.isna() | (cu.semana_pago > 8))).sum()
    assert fila.cuotas_vencidas == vencidas


def test_notas_solo_cuando_ya_se_tomaron(base):
    mx, est = matrices(base), estaticas(base)
    assert semana(mx, est, 3).nota_pc1.isna().all()
    s7 = semana(mx, est, 7)
    assert s7.nota_pc1.notna().any() and s7.nota_parcial.isna().all()
    assert (s7.evaluaciones_no_rendidas <= 1).all()


def test_panel_solo_activos_y_desenlace(pnl, base):
    assert set(pnl.semana) == set(range(2, 17))
    actual = pnl[pnl.periodo == base.periodo_actual]
    assert actual.semana.max() == 10 and actual.deserta.isna().all()
    cerrados = pnl[pnl.periodo != base.periodo_actual]
    assert cerrados.deserta.notna().all()
    # nadie aparece activo después de la semana en que dejó de ir
    assert not (cerrados.semana_abandono <= cerrados.semana).any()
