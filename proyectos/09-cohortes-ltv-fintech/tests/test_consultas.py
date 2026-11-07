import pandas as pd
import pytest

from cohortes import consultas as q


@pytest.fixture(scope="module")
def matriz(con):
    return q.matriz_cohortes(con)


@pytest.fixture(scope="module")
def tam(con):
    return q.tamanio_cohortes(con)


def test_mes_cero_tiene_a_todos(matriz):
    assert (matriz[matriz.k == 0].retencion == 1).all()


def test_solo_meses_cerrados(con, matriz):
    fin = pd.Timestamp(q.fin_observacion(con))
    ultimo = matriz.apply(lambda r: pd.Timestamp(r.cohorte) + pd.DateOffset(months=int(r.k)), axis=1)
    assert (ultimo <= fin).all()
    # la cohorte de setiembre 2026 llega hasta octubre (k = 1)
    ult = matriz[pd.to_datetime(matriz.cohorte) == pd.Timestamp("2026-09-01")]
    assert ult.k.max() == 1


def test_ingreso_acumulado_no_baja(matriz):
    d = matriz.groupby(["canal", "cohorte"]).ingreso_acum_cliente.diff().dropna()
    assert (d >= -1e-9).all()


def test_ingreso_cuadra_con_transacciones(con, matriz):
    total = con.execute("SELECT SUM(ingreso_neto) FROM transacciones").fetchone()[0]
    assert matriz.ingreso.sum() == pytest.approx(total, rel=1e-9)


def test_cac_es_gasto_sobre_activaciones(con, tam):
    fila = tam[(tam.canal == "Meta Ads")].iloc[3]
    gasto = con.execute("SELECT gasto_medios + gasto_bonos FROM gasto_marketing WHERE canal = 'Meta Ads' AND mes = ?",
                        [fila.cohorte]).fetchone()[0]
    assert fila.cac == pytest.approx(gasto / fila.clientes)
    assert (tam[tam.canal == "Orgánico"].cac == 0).all()


def test_payback_empirico():
    m = pd.DataFrame({"cohorte": ["c1"] * 4 + ["c2"] * 4, "canal": "X", "k": [0, 1, 2, 3] * 2,
                      "ingreso_acum_cliente": [2, 5, 9, 12, 1, 2, 3, 4], "clientes": 10})
    tam = pd.DataFrame({"cohorte": ["c1", "c2"], "canal": "X", "cac": [8.0, 8.0]})
    p = q.payback_empirico(m, tam).set_index("cohorte")
    assert p.loc["c1", "mes_payback"] == 2
    assert pd.isna(p.loc["c2", "mes_payback"]) and p.loc["c2", "cubierto_pct"] == 0.5


def test_ltv_empirico_solo_cohortes_con_un_anio(con, matriz):
    e = q.ltv_empirico(matriz, 12)
    fin = pd.Timestamp(q.fin_observacion(con))
    assert (pd.to_datetime(e.ultima) + pd.DateOffset(months=11) <= fin).all()
    assert set(e.canal) == set(matriz.canal)


def test_canales_de_redes_retienen_menos(matriz):
    r = q.retencion_promedio(matriz).set_index(["canal", "k"]).retencion
    assert r[("Referidos", 6)] > r[("Meta Ads", 6)] > r[("TikTok Ads", 6)]
