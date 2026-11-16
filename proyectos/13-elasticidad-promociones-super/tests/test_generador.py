import numpy as np
import pandas as pd

from generar_datos import generar


def test_tablas_y_tamanos(con):
    tablas = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    assert {"tiendas", "productos", "precios_semana", "ventas_semana", "promociones", "aux_promo_verdad"} <= tablas
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 40
    assert con.execute("SELECT COUNT(DISTINCT semana) FROM precios_semana").fetchone()[0] == 104
    formatos = {r[0] for r in con.execute("SELECT DISTINCT formato FROM tiendas").fetchall()}
    assert formatos == {"Hiper", "Super", "Express"}


def test_una_promocion_por_categoria_con_dos_semanas_de_separacion(con):
    pr = con.execute("""
        SELECT p.categoria, pr.inicio, pr.fin FROM promociones pr JOIN productos p USING (id_sku)
        ORDER BY 1, 2
    """).df()
    for _, g in pr.groupby("categoria"):
        inicio = pd.to_datetime(g.inicio).to_numpy()[1:]
        fin = pd.to_datetime(g.fin).to_numpy()[:-1]
        # la siguiente empieza después de las dos semanas en que se mide la caída
        assert ((inicio - fin) >= np.timedelta64(14, "D")).all()


def test_precio_de_venta_baja_solo_en_promocion(con):
    r = con.execute("""
        SELECT
          SUM((ps.precio_venta < ps.precio_regular AND pr.id_promo IS NULL)::INT) AS fuera,
          SUM((ps.precio_venta >= ps.precio_regular AND pr.id_promo IS NOT NULL)::INT) AS sin_bajar
        FROM precios_semana ps
        LEFT JOIN promociones pr ON pr.id_sku = ps.id_sku AND ps.semana BETWEEN pr.inicio AND pr.fin
    """).fetchone()
    assert r == (0, 0)


def test_verdad_sin_descuento_es_cero_y_canibaliza(con):
    v = con.execute("SELECT * FROM aux_promo_verdad").df()
    cero = v[v.descuento == 0]
    assert np.allclose(cero[["unid_propias", "margen_incremental", "venta_incremental"]], 0)
    con_desc = v[v.descuento > 0]
    assert (con_desc.unid_propias > 0).all()
    assert (con_desc.unid_canibalizadas < 0).all()
    assert (con_desc.unid_post <= 0).all()


def test_mismo_seed_misma_base(tmp_path):
    import duckdb
    tot = []
    for n in ("a", "b"):
        ruta = generar(tmp_path / f"{n}.duckdb", escala=0.2, seed=11)
        c = duckdb.connect(str(ruta), read_only=True)
        tot.append(c.execute("SELECT SUM(unidades) FROM ventas_semana").fetchone()[0])
        c.close()
    assert tot[0] == tot[1]
