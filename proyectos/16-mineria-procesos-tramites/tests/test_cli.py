import pytest

from tramites import cli
from tramites import resultados as Res


@pytest.fixture
def entorno(carpeta, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DATOS", carpeta)
    monkeypatch.setattr(cli, "EXPORTS", carpeta / "exports")
    monkeypatch.setattr(cli, "RESULTADOS", tmp_path / "resultados.duckdb")
    return tmp_path / "resultados.duckdb"


def test_analizar_y_simular(entorno):
    assert cli.main(["analizar"]) == 0
    assert cli.main(["simular", "--replicas", "2"]) == 0
    t = Res.tablas(entorno)
    assert {"casos", "arcos", "variantes", "por_area", "controles", "escenarios", "validacion"} <= t
    esc = Res.leer(entorno, "escenarios")
    assert set(esc["escenario"]) == {"actual", "e1", "e2", "e3", "e4"}
    casos = Res.leer(entorno, "casos")
    assert {"codigo_alumno", "nombre_alumno"} <= set(casos.columns)
    assert cli.main(["resumen"]) == 0
