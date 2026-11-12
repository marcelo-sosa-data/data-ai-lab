import json

import pytest

from semantico import cli


@pytest.fixture
def rutas(monkeypatch, carpeta_datos, tmp_path):
    monkeypatch.setattr(cli, "DATOS", carpeta_datos)
    monkeypatch.setattr(cli, "RESULTADOS", tmp_path / "resultados.json")
    monkeypatch.setattr(cli, "SALIDA", tmp_path / "salida")
    return tmp_path


def test_revisar_probar_legado(rutas):
    assert cli.main(["revisar"]) == 0
    assert cli.main(["probar"]) == 0
    assert cli.main(["legado"]) == 0
    res = json.loads((rutas / "resultados.json").read_text())
    assert res["reglas"] == [] and all(p["ok"] for p in res["pruebas"])
    assert len(res["legado"]["comparacion"]) == 11


def test_construir(rutas):
    assert cli.main(["construir", "--ambiente", "prod"]) == 0
    assert (rutas / "salida" / "prod" / "Matricula.SemanticModel" / "definition" / "model.tmdl").exists()


def test_sin_datos(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DATOS", tmp_path / "vacio")
    assert cli.main(["probar"]) == 1
