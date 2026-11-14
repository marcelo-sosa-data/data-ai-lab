import pandas as pd

from generar_datos import INCIDENTES, generar


def test_columnas_y_orden(dir_datos):
    ev = pd.read_parquet(dir_datos / "eventos.parquet")
    assert {"evento_id", "pedido_id", "zona", "tipo", "ts_evento", "ts_recibido"} <= set(ev.columns)
    assert ev["ts_recibido"].is_monotonic_increasing
    assert (ev["ts_recibido"] >= ev["ts_evento"]).all()
    assert set(ev["tipo"]) == {"creado", "asignado", "entregado", "cancelado"}


def test_reintentos_repiten_el_id(dir_datos):
    ev = pd.read_parquet(dir_datos / "eventos.parquet")
    rep = ev[ev["es_reintento"]]
    assert 0.01 < len(rep) / len(ev) < 0.05
    originales = ev[~ev["es_reintento"]].set_index("evento_id")
    assert rep["evento_id"].isin(originales.index).all()
    assert not originales.index.duplicated().any()


def test_cada_pedido_se_cierra_una_vez(dir_datos):
    ev = pd.read_parquet(dir_datos / "eventos.parquet")
    ev = ev[~ev["es_reintento"]]
    por_tipo = ev.pivot_table(index="pedido_id", columns="tipo", values="evento_id", aggfunc="count").fillna(0)
    assert (por_tipo["creado"] == 1).all()
    assert ((por_tipo["asignado"] + por_tipo["cancelado"]) == 1).all()
    assert (por_tipo["entregado"] == por_tipo["asignado"]).all()


def test_mas_atraso_en_zonas_con_mala_senal(dir_datos):
    ev = pd.read_parquet(dir_datos / "eventos.parquet")
    ev = ev[(ev["app"] == "motorizado") & ~ev["es_reintento"]]
    tarde = (ev["ts_recibido"] - ev["ts_evento"]).dt.total_seconds() > 60
    por_zona = tarde.groupby(ev["zona"]).mean()
    assert por_zona["SJL"] > 2 * por_zona["Miraflores"]


def test_incidentes_y_semilla(tmp_path, dir_datos):
    inc = pd.read_parquet(dir_datos / "incidentes.parquet")
    assert len(inc) == len(INCIDENTES)
    assert (inc["fin"] > inc["inicio"]).all()
    generar(tmp_path, escala=0.15, seed=11)
    a = pd.read_parquet(tmp_path / "eventos.parquet")
    b = pd.read_parquet(dir_datos / "eventos.parquet")
    pd.testing.assert_frame_equal(a, b)
