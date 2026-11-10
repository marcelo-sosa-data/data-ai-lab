import json

import duckdb

from reclamos.cli import main


def test_evaluar_juez_y_resumen(ruta_db, tmp_path, monkeypatch, capsys):
    resultados = tmp_path / "resultados.duckdb"
    monkeypatch.setenv("RECLAMOS_DB", str(ruta_db))
    monkeypatch.setenv("RECLAMOS_RESULTADOS", str(resultados))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert main(["evaluar", "--demo"]) == 0
    assert main(["juez", "--n", "60", "--solo-reglas"]) == 0
    assert main(["resumen"]) == 0
    salida = capsys.readouterr().out
    assert "Bien encaminados" in salida and "reglas" in salida
    con = duckdb.connect(str(resultados), read_only=True)
    corridas = dict(con.execute("SELECT corrida, datos FROM resumen").fetchall())
    assert {"as_is", "demo", "juez"} <= set(corridas)
    assert json.loads(corridas["demo"])["reclamos"] == 160
    assert con.execute("SELECT COUNT(*) FROM set_juez").fetchone()[0] > 30


def test_atender_un_reclamo(ruta_db, monkeypatch, capsys):
    monkeypatch.setenv("RECLAMOS_DB", str(ruta_db))
    assert main(["atender", "1", "--demo", "--detalle"]) == 0
    assert "R-26-00001" in capsys.readouterr().out
