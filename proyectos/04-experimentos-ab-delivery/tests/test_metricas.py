import duckdb
import pandas as pd

from experimentos.metricas import acumulado_diario, tabla_usuarios


def _base(tmp_path):
    ruta = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(ruta))
    con.execute("""CREATE TABLE usuarios AS SELECT * FROM (VALUES
        (1, 'Lima', 'ios', 'ios', DATE '2025-01-01'),
        (2, 'Piura', 'android', 'android<6', DATE '2026-02-25'),
        (3, 'Lima', 'android', 'android>=6', DATE '2025-06-01'))
        t(id_usuario, ciudad, plataforma, version_app, fecha_registro)""")
    con.execute("""CREATE TABLE exposiciones AS SELECT * FROM (VALUES
        ('EXP-X', 1, 'control', DATE '2026-03-05'),
        ('EXP-X', 2, 'tratamiento', DATE '2026-03-02'),
        ('EXP-X', 3, 'tratamiento', DATE '2026-03-20'))
        t(id_experimento, id_usuario, variante, fecha_exposicion)""")
    con.execute("""CREATE TABLE pedidos AS SELECT * FROM (VALUES
        (1, DATE '2026-02-10', 30.0, 5.0, false),  -- pre
        (1, DATE '2026-03-04', 40.0, 6.0, false),  -- antes de exponerse: no cuenta
        (1, DATE '2026-03-05', 50.0, 7.0, false),
        (1, DATE '2026-03-10', 20.0, 0.0, true),   -- cancelado
        (1, DATE '2026-03-30', 99.0, 9.0, false),  -- después del fin
        (2, DATE '2026-03-02', 25.0, 4.0, false),
        (2, DATE '2026-03-02', 35.0, 5.0, false))
        t(id_usuario, fecha, monto, margen, cancelado)""")
    return con


def test_ventana_de_exposicion(tmp_path):
    con = _base(tmp_path)
    u = tabla_usuarios(con, "EXP-X", "2026-03-02", "2026-03-29").set_index("id_usuario")
    assert u.loc[1, "pedidos"] == 1 and u.loc[1, "gmv"] == 50.0
    assert u.loc[1, "pedidos_creados"] == 2 and u.loc[1, "cancelados"] == 1
    assert u.loc[1, "pedidos_pre"] == 1 and u.loc[1, "gmv_pre"] == 30.0
    assert u.loc[2, "pedidos"] == 2 and u.loc[2, "margen"] == 9.0
    assert u.loc[3, "pedidos"] == 0 and u.loc[3, "conversion"] == 0
    assert bool(u.loc[1, "recurrente"]) and not bool(u.loc[2, "recurrente"])
    assert u.loc[2, "region"] == "provincia"


def test_acumulado_diario(tmp_path):
    con = _base(tmp_path)
    u = tabla_usuarios(con, "EXP-X", "2026-03-02", "2026-03-29")
    dias, acum, expo = acumulado_diario(con, "EXP-X", u, "2026-03-02", "2026-03-29")
    assert len(dias) == 28
    i1 = u.index[u.id_usuario == 1][0]
    assert acum[i1, 2] == 0 and acum[i1, 3] == 1 and acum[i1, -1] == 1  # 05/03 es el día 4
    assert not expo[i1, 2] and expo[i1, 3]
    i2 = u.index[u.id_usuario == 2][0]
    assert acum[i2, 0] == 2
    assert pd.Timestamp(dias[-1]) == pd.Timestamp("2026-03-29")
