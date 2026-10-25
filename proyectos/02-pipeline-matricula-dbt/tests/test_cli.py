from matricula.cli import main


def test_calidad_cuadra_con_lo_inyectado(build):
    assert main(["calidad"]) == 0


def test_resumen(build, capsys):
    assert main(["resumen"]) == 0
    assert "Alumnos matriculados" in capsys.readouterr().out


def test_sin_base_da_mensaje_claro(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MATRICULA_DB", str(tmp_path / "no_existe.duckdb"))
    assert main(["resumen"]) == 2
    assert "python -m matricula build" in capsys.readouterr().out
