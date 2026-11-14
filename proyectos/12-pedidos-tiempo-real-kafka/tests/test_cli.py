import pedidos_rt.cli as cli


def test_generar_y_resumen_sin_resultados(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "DIR_DATOS", tmp_path)
    cli.main(["generar", "--escala", "0.05"])
    assert (tmp_path / "eventos.parquet").exists()
    assert (tmp_path / "incidentes.parquet").exists()
    cli.main(["resumen"])
    assert "No hay resultados" in capsys.readouterr().out
