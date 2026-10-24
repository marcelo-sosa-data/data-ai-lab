import duckdb
import pytest


def test_tablas_esperadas(db):
    assert db.tablas == {"tiendas", "categorias", "productos", "clientes", "ventas", "detalle_venta"}


def test_la_conexion_es_de_solo_lectura(db):
    # aunque el guard fallara, la base no se puede modificar
    with pytest.raises(duckdb.Error):
        db.con.execute("DELETE FROM ventas")


def test_describir_tabla_lista_valores_de_texto(db):
    info = db.describir_tabla("ventas")
    medio = next(c for c in info["columnas"] if c["columna"] == "medio_pago")
    assert "Yape" in medio["valores"]
    assert "descripcion" in medio
    assert len(info["ejemplos"]) == 3


def test_describir_tabla_inexistente(db):
    assert "error" in db.describir_tabla("usuarios")


def test_ejecutar_devuelve_filas(db):
    r = db.ejecutar("SELECT ciudad, COUNT(*) n FROM tiendas GROUP BY ciudad ORDER BY n DESC")
    assert r.ok and r.columnas == ["ciudad", "n"]
    assert r.filas[0][0] == "Lima"


def test_ejecutar_trunca_resultados_grandes(db):
    r = db.ejecutar("SELECT * FROM detalle_venta LIMIT 1000")
    assert r.ok and r.truncado and len(r.filas) == 50


def test_error_de_sql_se_devuelve_legible(db):
    r = db.ejecutar("SELECT columna_que_no_existe FROM ventas")
    assert not r.ok and "columna_que_no_existe" in r.error


def test_importe_cuadra_con_cantidad_y_descuento(db):
    r = db.ejecutar("""
        SELECT COUNT(*) FROM detalle_venta
        WHERE ABS(importe - cantidad * precio_unitario * (1 - descuento_pct)) > 0.011
    """)
    assert r.filas[0][0] == 0


def test_no_hay_ventas_antes_de_la_apertura(db):
    r = db.ejecutar("""
        SELECT COUNT(*) FROM ventas v JOIN tiendas t USING (id_tienda)
        WHERE v.fecha_hora::DATE < t.fecha_apertura
    """)
    assert r.filas[0][0] == 0
