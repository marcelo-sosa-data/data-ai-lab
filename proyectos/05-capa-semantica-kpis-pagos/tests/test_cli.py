import duckdb
import pytest

from kpis.cli import main


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("TINKUY_DB", str(tmp_path / "t.duckdb"))
    monkeypatch.setenv("TINKUY_RESULTADOS", str(tmp_path / "r.duckdb"))
    return tmp_path


def test_flujo_completo(entorno, capsys):
    assert main(["todo", "--escala", "0.12", "--seed", "3"]) == 0
    con = duckdb.connect(str(entorno / "r.duckdb"), read_only=True)
    tablas = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    metricas = {r[0] for r in con.execute("SELECT DISTINCT metrica FROM serie").fetchall()}
    con.close()
    assert {"serie", "eventos", "evaluacion", "falsas", "explicaciones", "corrida"} <= tablas
    assert metricas == {"tpv", "transacciones", "tasa_aprobacion"}
    assert main(["consultar", "tpv", "take_rate", "--por", "metodo", "--grano", "trimestre"]) == 0
    assert main(["explicar", "tasa_aprobacion", "--fecha", "2026-08-14"]) == 0
    assert main(["explicar", "ticket_promedio", "--periodo", "2026-08", "--contra", "2026-04"]) == 0
    salida = capsys.readouterr().out
    assert "Banco del Pacífico" in salida and "cuadra" in salida


def test_sql_en_otro_dialecto_sin_base(entorno, capsys):
    assert main(["consultar", "tasa_aprobacion", "--por", "rubro", "--grano", "mes", "--dialecto", "snowflake"]) == 0
    assert "DATE_TRUNC('MONTH'" in capsys.readouterr().out


def test_sin_datos_avisa(entorno, capsys):
    assert main(["validar"]) == 1
    assert "generar" in capsys.readouterr().out


def test_errores_de_la_capa_se_muestran(entorno, capsys):
    main(["generar", "--escala", "0.05"])
    assert main(["consultar", "tpv", "--por", "distrito"]) == 1
    assert main(["consultar", "tpv", "--donde", "region"]) == 1
    assert main(["explicar", "tpv"]) == 1
    salida = capsys.readouterr().out
    assert "distrito no existe" in salida and "dimension=valor" in salida and "--periodo" in salida
