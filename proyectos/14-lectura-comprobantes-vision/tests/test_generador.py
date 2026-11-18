from datetime import date

import numpy as np

from comprobantes.reglas import ruc_valido


def test_volumen_y_periodo(tablas):
    v = tablas["aux_verdad"]
    assert 50 < len(v) < 150
    assert v["fecha_recepcion"].min().date() >= date(2026, 9, 1)
    assert v["fecha_recepcion"].max().date() <= date(2026, 10, 31)
    assert (v["fecha_emision"] <= v["fecha_recepcion"]).all()


def test_rucs_validos_y_receptor(tablas):
    v, empresa = tablas["aux_verdad"], tablas["empresa"]["ruc"].iloc[0]
    assert v["ruc_emisor"].map(ruc_valido).all()
    facturas = v[v["tipo"] == "factura"]
    bien = facturas[facturas["anomalia"] != "receptor_errado"]
    assert (bien["ruc_receptor"] == empresa).all()
    assert v.loc[v["tipo"] == "boleta", "ruc_receptor"].isna().all()


def test_aritmetica_cuadra_salvo_errores_sembrados(tablas):
    v = tablas["aux_verdad"]
    sanos = v[~v["anomalia"].isin(["igv_mal", "total_mal"])]
    assert np.allclose(sanos["igv"], (sanos["base_imponible"] * 0.18).round(2), atol=0.011)
    assert np.allclose(sanos["total"], sanos["base_imponible"] + sanos["igv"], atol=0.011)
    igv_mal = v[v["anomalia"] == "igv_mal"]
    assert ((igv_mal["igv"] - igv_mal["base_imponible"] * 0.18).abs() > 0.1).all()


def test_ordenes_de_compra(tablas):
    v, oc = tablas["aux_verdad"], tablas["ordenes_compra"].set_index("orden_compra")
    con_oc = v[v["orden_compra"].notna()]
    assert con_oc["orden_compra"].isin(oc.index).all()
    monto = con_oc["orden_compra"].map(oc["monto"])
    excede = con_oc["anomalia"] == "excede_oc"
    assert (con_oc.loc[excede, "total"] > monto[excede] * 1.01).all()
    normales = con_oc[~excede & (con_oc["anomalia"] != "duplicado")]
    assert (normales["total"] <= normales["orden_compra"].map(oc["monto"]) + 0.01).all()


def test_duplicados_apuntan_al_original(tablas):
    v = tablas["aux_verdad"].set_index("doc_id")
    for doc_id, orig in v.loc[v["anomalia"] == "duplicado", "duplicado_de"].items():
        a, b = v.loc[doc_id], v.loc[int(orig)]
        assert (a["serie"], a["numero"], a["total"]) == (b["serie"], b["numero"], b["total"])
        assert a["fecha_recepcion"] > b["fecha_recepcion"]


def test_imagenes_existen(ruta_db, tablas):
    carpeta = ruta_db.parent / "imagenes"
    assert all((carpeta / a).exists() for a in tablas["recepcion"]["archivo"])


def test_reproducible(tmp_path, tablas):
    from generar_datos import generar
    import duckdb

    ruta = generar(tmp_path / "otra.duckdb", escala=0.08, seed=7, imagenes=False)
    otra = duckdb.connect(str(ruta), read_only=True).execute("SELECT * FROM aux_verdad").df()
    cols = ["doc_id", "ruc_emisor", "serie", "numero", "total", "anomalia"]
    assert otra[cols].equals(tablas["aux_verdad"][cols])
