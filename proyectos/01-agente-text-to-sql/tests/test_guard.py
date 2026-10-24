import pytest

from text2sql.guard import validar_sql

TABLAS = {"ventas", "detalle_venta", "tiendas", "productos", "categorias", "clientes"}


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM ventas",
    "select * from tiendas where ciudad = 'Lima';",
    "WITH t AS (SELECT id_tienda FROM tiendas) SELECT * FROM t",
    "SELECT nombre FROM tiendas UNION ALL SELECT nombre FROM productos",
    "SELECT v.id_venta FROM ventas v WHERE v.id_tienda IN (SELECT id_tienda FROM tiendas)",
    "SELECT DATE_TRUNC('month', fecha_hora) m, COUNT(*) FROM ventas GROUP BY 1",
    "SELECT medio_pago, COUNT(*) FILTER (WHERE id_cliente IS NOT NULL) FROM ventas GROUP BY ALL",
])
def test_permite_consultas_de_lectura(sql):
    r = validar_sql(sql, TABLAS)
    assert r.ok, r.motivo


@pytest.mark.parametrize("sql, contiene", [
    ("DELETE FROM ventas", "SELECT"),
    ("DROP TABLE ventas", "SELECT"),
    ("UPDATE productos SET precio_lista = 0", "SELECT"),
    ("INSERT INTO tiendas VALUES (99, 'x', 'x', 'x', 'x', '2026-01-01')", "SELECT"),
    ("CREATE TABLE x AS SELECT * FROM ventas", "SELECT"),
    ("SELECT 1; DROP TABLE ventas", "una sentencia"),
    ("COPY ventas TO 'fuga.csv'", "SELECT"),
    ("ATTACH 'otra.db'", "SELECT"),
    ("PRAGMA database_list", "SELECT"),
    ("SET threads = 1", "SELECT"),
    ("INSTALL httpfs", "SELECT"),
    ("SELECT * FROM read_csv('/etc/passwd')", "funciones de tabla"),
    ("SELECT * FROM 'datos.csv'", "no existe"),
    ("SELECT getenv('LLM_API_KEY')", "getenv"),
    ("SELECT * FROM query('DROP TABLE ventas')", "funciones de tabla"),
    ("SELECT * FROM duckdb_settings()", "funciones de tabla"),
    ("SELECT * FROM usuarios", "no existe"),
    ("SELECT * FROM otra_db.main.ventas", "otros esquemas"),
    ("", "vacía"),
    ("SELEC * FORM ventas", ""),
])
def test_bloquea_lo_peligroso(sql, contiene):
    r = validar_sql(sql, TABLAS)
    assert not r.ok
    assert contiene.lower() in r.motivo.lower()


def test_agrega_limit_si_no_hay():
    r = validar_sql("SELECT * FROM ventas", TABLAS, limite=100)
    assert "LIMIT 100" in r.sql


def test_respeta_limit_existente():
    r = validar_sql("SELECT * FROM ventas LIMIT 5", TABLAS, limite=100)
    assert "LIMIT 5" in r.sql and "LIMIT 100" not in r.sql


def test_limit_en_union_envuelve_la_consulta():
    r = validar_sql("SELECT nombre FROM tiendas UNION SELECT nombre FROM productos", TABLAS, 10)
    assert r.ok and r.sql.rstrip().endswith("LIMIT 10")
