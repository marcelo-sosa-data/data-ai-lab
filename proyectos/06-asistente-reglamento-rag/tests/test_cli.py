import json

import pytest

from reglamento import cli


@pytest.fixture
def datos(rutas, monkeypatch):
    monkeypatch.setenv("REGLAMENTO_DATOS", str(rutas["corpus"].parent))
    return rutas


def test_corpus(datos, capsys):
    cli.main(["corpus"])
    salida = capsys.readouterr().out
    assert "RE-2024" in salida and "6, 10, 17, 18, 25" in salida and "35-A" in salida


def test_preguntar_en_modo_demo_sin_vectores(datos, capsys):
    cli.main(["preguntar", "si pago tarde la cuota cuanto me cobran de mas?", "--demo", "--sin-vectores",
              "--fecha", "2026-09-01", "--detalle"])
    salida = capsys.readouterr().out
    assert "RP-2025, art. 5" in salida and "Respuesta" in salida


def test_umbral_se_lee_del_resumen(datos):
    carpeta = datos["corpus"].parent / "resultados"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "resumen.json").write_text(json.dumps({"umbrales": {"bm25+sinonimos": {"umbral": 4.2}}}))
    assert cli.leer_umbral(cli.SIN_VECTORES, None) == 4.2
    assert cli.leer_umbral(cli.DEFECTO, "otro-modelo") == 0.0
    (carpeta / "resumen.json").unlink()
