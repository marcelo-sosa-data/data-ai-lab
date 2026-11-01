import numpy as np
import pandas as pd
import pytest

from kpis.explicacion import concentracion, descomponer, explicar_dia, explicar_periodos
from kpis.modelo import ErrorSemantico


def _df(n, d, idx):
    return pd.DataFrame({"n": n, "d": d}, index=idx, dtype=float)


def test_mezcla_mas_tasa_es_el_cambio_exacto():
    rng = np.random.default_rng(0)
    idx = list("abcdef")
    for _ in range(50):
        d0, d1 = rng.integers(50, 500, 6), rng.integers(50, 500, 6)
        b, a = _df(rng.binomial(d0, 0.9), d0, idx), _df(rng.binomial(d1, 0.85), d1, idx)
        det = descomponer(b, a, "n", "d")
        delta = a.n.sum() / a.d.sum() - b.n.sum() / b.d.sum()
        assert det.contribucion.sum() == pytest.approx(delta, abs=1e-12)


def test_segmento_nuevo_es_mezcla_pura():
    b = _df([90, 90], [100, 100], ["5.10", "5.11"])
    a = _df([90, 90, 70], [100, 100, 100], ["5.10", "5.11", "5.12"])
    det = descomponer(b, a, "n", "d")
    assert det.loc["5.12", "efecto_tasa"] == 0
    assert det.loc["5.12", "efecto_mezcla"] == pytest.approx(1 / 3 * (0.7 - 0.9))
    assert det.contribucion.sum() == pytest.approx(250 / 300 - 0.9)


def test_simpson_mezcla_baja_aunque_todos_suben():
    b = _df([1000, 4000], [100, 100], ["bodega", "ropa"])     # tickets 10 y 40
    a = _df([3300, 4200], [300, 100], ["bodega", "ropa"])     # tickets 11 y 42
    det = descomponer(b, a, "n", "d")
    assert (det.valor_actual > det.valor_base).all()
    assert det.contribucion.sum() < 0
    assert det.efecto_mezcla.sum() < 0 < det.efecto_tasa.sum()


def test_concentracion():
    idx = list("abcd")
    b = _df([100, 200, 300, 400], [1, 1, 1, 1], idx)
    parejo = descomponer(b, b * 0.9, "n", None)
    uno = descomponer(b, _df([0, 200, 300, 400], [1, 1, 1, 1], idx), "n", None)
    assert concentracion(parejo) == pytest.approx(0, abs=1e-12)
    # cae solo "a": su exceso es -100 + 5 (le tocaba su peso promedio, 5%) sobre 100 movidos
    assert concentracion(uno) == pytest.approx(0.95)


def test_ubica_el_emisor_caido(capa, con):
    e = explicar_dia(capa, con, "tasa_aprobacion", "2026-08-14")
    assert e.cambio < -0.02
    top2 = e.ranking.head(2)
    assert "Banco del Pacífico" in set(top2.segmento)
    hora = e.ranking.set_index("dimension").loc["hora"]
    assert hora.concentracion > 0.4 and set(hora.segmento.split(", ")) <= {"11", "12", "13", "14", "15"}


def test_ubica_la_carga_que_falto(capa, con):
    # con un cuarto del volumen el ruido de otras dimensiones compite; a escala completa sale primera
    e = explicar_dia(capa, con, "transacciones", "2026-05-20")
    r = e.ranking.head(2).set_index("dimension")
    assert r.loc["region", "segmento"] == "Arequipa"
    assert e.detalle["region"].loc["Arequipa", "valor_actual"] == 0


def test_ubica_la_version_con_bug(capa, con):
    e = explicar_dia(capa, con, "tasa_aprobacion", "2026-09-08")
    v = e.ranking.set_index("dimension").loc["version_app"]
    assert v.segmento == "5.12" and v.concentracion > 0.4


def test_aditivas_no_usan_dimensiones_que_derivan(capa, con):
    e = explicar_dia(capa, con, "tpv", "2026-05-20")
    assert not {"version_app", "cohorte", "estado"} & set(e.ranking.dimension)
    e = explicar_dia(capa, con, "tasa_aprobacion", "2026-05-20")
    assert "version_app" in set(e.ranking.dimension) and "estado" not in set(e.ranking.dimension)


def test_ticket_baja_por_mezcla(capa, con):
    e = explicar_periodos(capa, con, "ticket_promedio", ("2026-08-01", "2026-08-31"),
                          ("2026-04-01", "2026-04-30"), ["rubro", "canal_alta"])
    assert e.cambio < 0
    r = e.ranking.set_index("dimension")
    assert r.loc["rubro", "efecto_mezcla"] < e.cambio * 0.8
    assert r.loc["canal_alta", "segmento"] == "bodega_digital"


def test_no_descompone_conteos_distintos(capa, con):
    with pytest.raises(ErrorSemantico, match="no se puede descomponer"):
        explicar_dia(capa, con, "comercios_activos", "2026-08-14")
