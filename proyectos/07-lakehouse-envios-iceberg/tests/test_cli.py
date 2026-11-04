import pytest

from lakehouse import catalogo
from lakehouse.cli import main


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("KALLPA_DATOS", str(tmp_path))
    return tmp_path


def test_flujo_completo(entorno, capsys):
    # del 13 al 18 de setiembre: entra franja_horaria en origen (15) y en el contrato (17)
    assert main(["todo", "--escala", "0.05", "--desde", "2026-09-13", "--hasta", "2026-09-18"]) == 0
    salida = capsys.readouterr().out
    assert "columnas fuera del contrato" in salida and "plata.envios agrega franja_horaria" in salida
    assert "cuadra" in salida and "no cuadra" not in salida
    assert main(["estado"]) == 0
    assert "cortes etiquetados" in capsys.readouterr().out
    assert main(["viaje", "--promesa", "2026-09-15"]) == 0
    assert "OTD" in capsys.readouterr().out
    id_envio = catalogo.tablas()["plata"].scan(selected_fields=("id_envio",), limit=1).to_arrow()["id_envio"][0]
    assert main(["envio", str(id_envio.as_py())]) == 0
    assert "Historial de estados" in capsys.readouterr().out
    assert main(["mantener"]) == 0
    assert main(["correr"]) == 0
    assert "No hay lotes pendientes" in capsys.readouterr().out


def test_sin_datos_avisa(entorno, capsys):
    assert main(["correr"]) == 1
    assert main(["estado"]) == 1
    salida = capsys.readouterr().out
    assert "generar" in salida and "correr" in salida
