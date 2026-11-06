import duckdb
import pytest

from desercion.cli import main


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("DESERCION_DB", str(tmp_path / "u.duckdb"))
    monkeypatch.setenv("DESERCION_RESULTADOS", str(tmp_path / "r.duckdb"))
    return tmp_path


def test_flujo_completo(entorno):
    assert main(["generar", "--escala", "0.12", "--seed", "5"]) == 0
    assert main(["entrenar", "--rondas", "40"]) == 0
    assert main(["supervivencia"]) == 0
    assert main(["lista", "--n", "5", "--sede", "Arequipa"]) == 0
    con = duckdb.connect(str(entorno / "r.duckdb"), read_only=True)
    tablas = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    assert {"metricas_semana", "capacidad", "lista", "shap_actual", "ausentes", "km", "cox"} <= tablas
    puestos = con.execute("SELECT puesto, puntaje FROM lista ORDER BY puesto").df()
    sem = con.execute("SELECT DISTINCT semana FROM riesgo_actual ORDER BY 1").df().semana.tolist()
    con.close()
    assert puestos.puntaje.is_monotonic_decreasing
    assert sem == list(range(2, 11))


def test_sin_datos_avisa(entorno, capsys):
    assert main(["entrenar"]) == 1
    assert "generar" in capsys.readouterr().out
    assert main(["lista"]) == 1
