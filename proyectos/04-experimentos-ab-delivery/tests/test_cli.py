import duckdb
import pytest

from experimentos.cli import main


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("CHASQUI_DB", str(tmp_path / "c.duckdb"))
    monkeypatch.setenv("CHASQUI_RESULTADOS", str(tmp_path / "r.duckdb"))
    monkeypatch.setenv("CHASQUI_REPORTES", str(tmp_path / "reportes"))
    return tmp_path


def test_flujo_completo(entorno):
    assert main(["todo", "--escala", "0.15", "--seed", "3", "--repeticiones", "100"]) == 0
    con = duckdb.connect(str(entorno / "r.duckdb"), read_only=True)
    tablas = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    veredictos = dict(con.execute("SELECT id_experimento, veredicto FROM resumen").fetchall())
    con.close()
    assert {"resumen", "metricas", "segmentos", "semanas", "secuencial", "aa_curva", "planificacion"} <= tablas
    assert len(veredictos) == 5
    assert set(veredictos.values()) <= {"lanzar", "no lanzar", "extender", "invalidar"}
    md = (entorno / "reportes" / "EXP-04.md").read_text(encoding="utf-8")
    assert md.startswith("# EXP-04") and "## Guardrails" in md and "Veredicto" in md


def test_sin_datos_avisa(entorno, capsys):
    assert main(["analizar"]) == 1
    assert "generar" in capsys.readouterr().out


def test_experimento_que_no_existe(entorno, capsys):
    main(["generar", "--escala", "0.05"])
    assert main(["reporte", "EXP-99"]) == 1
    assert "EXP-01" in capsys.readouterr().out
