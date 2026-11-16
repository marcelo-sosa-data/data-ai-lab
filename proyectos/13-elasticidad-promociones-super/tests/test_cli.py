from elasticidad import cli


def test_resumen_sin_resultados(tmp_path, monkeypatch):
    monkeypatch.setenv("ELASTICIDAD_RESULTADOS", str(tmp_path / "no_hay.duckdb"))
    assert cli.main(["resumen"]) == 1


def test_simular_sin_modelo(ruta_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ELASTICIDAD_DB", str(ruta_db))
    monkeypatch.setenv("ELASTICIDAD_MODELOS", str(tmp_path / "vacio"))
    assert cli.main(["simular", "--sku", "501", "--inicio", "2026-11-16", "--descuento", "0.2"]) == 1


def test_simular_con_modelo(ruta_db, ajuste, tmp_path, monkeypatch, capsys):
    from elasticidad import modelo as M
    post, meta, diag = ajuste
    M.guardar(tmp_path, "final", post, meta, diag)
    monkeypatch.setenv("ELASTICIDAD_DB", str(ruta_db))
    monkeypatch.setenv("ELASTICIDAD_MODELOS", str(tmp_path))
    assert cli.main(["simular", "--sku", "501", "--inicio", "2026-11-16", "--descuento", "0.2", "--encarte"]) == 0
    assert "probabilidad de ganar margen" in capsys.readouterr().out
