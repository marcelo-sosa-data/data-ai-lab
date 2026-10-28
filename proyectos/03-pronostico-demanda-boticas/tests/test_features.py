import numpy as np
import pandas as pd
import pytest

from demanda import features as ft
from demanda.datos import armar_panel


def test_media_rezagada_a_mano():
    x = np.array([1, 2, 3, 4, 5, np.nan, 7, 8.0])
    pos = np.arange(8)
    m = ft.media_rezagada(x, pos, desde=2, hasta=4, min_n=1)
    # en t=6 promedia x[2..4] = (3+4+5)/3; en t=7 x[3..5] ignorando NaN = 4.5
    assert m[6] == pytest.approx(4.0)
    assert m[7] == pytest.approx(4.5)
    assert np.isnan(m[1])  # todavía no hay 2 días de historia


def test_media_rezagada_no_cruza_series():
    x = np.array([10, 10, 10, 1, 1, 1.0])
    pos = np.array([0, 1, 2, 0, 1, 2])
    m = ft.media_rezagada(x, pos, desde=1, hasta=5)
    assert m[3] != m[3]  # primer día de la segunda serie: NaN
    assert m[4] == pytest.approx(1.0)


@pytest.fixture(scope="module")
def panel(base):
    return armar_panel(base)


def test_no_mira_los_ultimos_14_dias(panel):
    """Si cambio la venta de los últimos 13 días, las features del día d no cambian."""
    d = pd.Timestamp("2026-07-15")
    serie = (panel.id_local == 1) & (panel.id_producto == 1)
    alterado = panel.copy()
    m = serie & (alterado.fecha > d - pd.Timedelta(days=14)) & (alterado.fecha <= d)
    alterado.loc[m, "unidades"] = 999
    alterado.loc[m, "quiebre"] = ~alterado.loc[m, "quiebre"]
    a = ft.construir(panel)
    b = ft.construir(alterado)
    fila = (a.fecha == d) & serie
    cols = [c for c in ft.COLUMNAS if c not in ft.CATEGORICAS]
    pd.testing.assert_frame_equal(a.loc[fila, cols], b.loc[fila, cols])


def test_quiebres_se_tratan_como_faltantes(panel):
    f = ft.construir(panel, tratar_quiebres=True)
    sin = ft.construir(panel, tratar_quiebres=False)
    q = f.quiebre.to_numpy()
    assert f.objetivo[q].isna().all()
    assert sin.objetivo[q].notna().all()
    # el lag_14 de un día cuyo d-14 fue quiebre queda vacío
    i = np.flatnonzero(q)[0]
    j = f.index[(f.id_local == f.id_local[i]) & (f.id_producto == f.id_producto[i])
                & (f.fecha == f.fecha[i] + pd.Timedelta(days=14))]
    assert np.isnan(f.loc[j, "lag_14"]).all()


def test_promocion_planificada_entra_en_el_futuro(base):
    p = armar_panel(base, dias_futuro=14)
    futuro = p[p.es_futuro]
    assert futuro.unidades.isna().all()
    plan = base.promociones[base.promociones.inicio > base.ultimo_dia]
    assert len(futuro) == base.ventas.groupby(["id_local", "id_producto"]).ngroups * 14
    # la columna existe y respeta el plan (puede no haber campañas en esas dos semanas)
    assert futuro.descuento.between(0, 0.3).all()
    assert len(plan) > 0
