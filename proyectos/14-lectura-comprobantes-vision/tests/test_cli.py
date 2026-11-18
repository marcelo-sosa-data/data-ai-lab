import sys

import duckdb
import pytest
from conftest import HAY_TESSERACT

from comprobantes import cli


def correr(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["comprobantes", *args])
    cli.main()


@pytest.mark.skipif(not HAY_TESSERACT, reason="sin tesseract instalado")
def test_flujo_completo_en_modo_demo(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COMPROBANTES_DB", str(tmp_path / "tayta.duckdb"))
    monkeypatch.setenv("COMPROBANTES_RESULTADOS", str(tmp_path / "resultados.duckdb"))
    monkeypatch.setenv("COLUMNS", "150")
    correr(monkeypatch, "generar", "--escala", "0.04", "--seed", "3")
    correr(monkeypatch, "leer", "--demo", "--procesos", "1")
    correr(monkeypatch, "evaluar")
    salida = capsys.readouterr().out
    assert "Exactitud por campo" in salida and "AS IS" in salida

    con = duckdb.connect(str(tmp_path / "resultados.duckdb"), read_only=True)
    n_lect, n_dec = con.execute(
        "SELECT (SELECT COUNT(*) FROM lecturas), (SELECT COUNT(*) FROM decisiones)").fetchone()
    assert n_lect == n_dec > 0
    assert con.execute("SELECT COUNT(*) FROM curva_umbral").fetchone()[0] > 0

    correr(monkeypatch, "resumen")
    correr(monkeypatch, "ver", "1", "--demo")
    assert "Destino" in capsys.readouterr().out


def test_sin_clave_y_sin_demo_avisa(monkeypatch, tmp_path, ruta_db, capsys):
    monkeypatch.setenv("COMPROBANTES_DB", str(ruta_db))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(cli, "cargar_env", lambda *a: None)
    with pytest.raises(SystemExit):
        correr(monkeypatch, "leer", "--n", "5")
    assert "LLM_API_KEY" in capsys.readouterr().out


def test_resumen_sin_resultados(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COMPROBANTES_RESULTADOS", str(tmp_path / "vacio.duckdb"))
    duckdb.connect(str(tmp_path / "vacio.duckdb")).execute(
        "CREATE TABLE resumen (datos VARCHAR, corrida VARCHAR)").close()
    with pytest.raises(SystemExit):
        correr(monkeypatch, "resumen")
