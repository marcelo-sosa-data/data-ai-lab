import pytest

from admision.pruebas import Prueba, cargar, correr, hay_bloqueo


def test_las_pruebas_tienen_encabezado():
    pruebas = cargar()
    assert len(pruebas) >= 15
    assert {p.severidad for p in pruebas} == {"error", "aviso"}


def test_datos_limpios_pasan(con):
    resultados = correr(con)
    assert not hay_bloqueo(resultados), [r.nombre for r in resultados if r.bloquea]


def test_prueba_que_no_corre_cuenta_como_fallida(con):
    r = correr(con, [Prueba("rota", "error", "x", "SELECT * FROM tabla_que_no_existe")])[0]
    assert r.bloquea and "tabla_que_no_existe" in r.error_sql


def test_aviso_no_bloquea(con):
    r = correr(con, [Prueba("aviso", "aviso", "x", "SELECT 1")])
    assert not r[0].aprobada and not hay_bloqueo(r)


def test_encabezado_obligatorio(tmp_path):
    (tmp_path / "x.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ValueError):
        cargar(tmp_path)
