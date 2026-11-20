from datetime import date

import duckdb

from admision.comparar import cifras, pendientes, proyeccion
from admision.publicar import etiqueta_dia, etiqueta_fecha, publicar
from admision.pruebas import correr


def test_etiquetas_en_espanol():
    assert etiqueta_dia(date(2026, 9, 6)) == "6 set"
    assert etiqueta_fecha(date(2026, 11, 15)) == "15 nov 2026"


def test_publica_una_base_que_lee_un_duckdb_anterior(con, tmp_path):
    destino = publicar(con, correr(con), tmp_path / "admision.duckdb")
    lector = duckdb.connect(str(destino), read_only=True)
    tablas = {t[0] for t in lector.sql("SHOW TABLES").fetchall()}
    assert {"kpi_campania", "avance_comparado", "resultados_pruebas", "publicacion"} <= tablas
    series = lector.sql("SELECT DISTINCT serie FROM avance_comparado").fetchall()
    assert len(series) == 2
    etiquetas = lector.sql("SELECT etiqueta FROM avance_comparado WHERE semana = 1").fetchall()
    assert len({e[0] for e in etiquetas}) == 1
    lector.close()


def test_comparaciones(con, carpeta):
    df = cifras(con, carpeta / "crudo", carpeta / "verdad")
    assert (df.loc[df["medida"] == "postulantes", "error_to_be"] == 0).all()
    pen = pendientes(con, carpeta / "crudo", carpeta / "verdad").set_index("reporte")
    assert pen.loc["as_is", "pct_inutiles"] > pen.loc["to_be", "pct_inutiles"]
    proy = proyeccion(con, carpeta / "verdad")
    assert proy["al_cierre"].notna().all() and len(proy) == 3
