from cohortes import cli
from cohortes.resultados import leer, tablas


def test_todo_de_una_base_chica(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COHORTES_DB", str(tmp_path / "ayni.duckdb"))
    monkeypatch.setenv("COHORTES_RESULTADOS", str(tmp_path / "resultados.duckdb"))
    assert cli.main(["todo", "--escala", "0.08", "--seed", "9"]) == 0
    t = tablas(tmp_path / "resultados.duckdb")
    assert {"matriz", "payback_cohortes", "val_general", "val_semanal", "ltv_canales", "base_actual"} <= t
    ltv = leer(tmp_path / "resultados.duckdb", "ltv_canales").set_index("canal")
    assert ltv.loc["Referidos", "ltv_cac_24"] > ltv.loc["TikTok Ads", "ltv_cac_24"]
    assert cli.main(["resumen"]) == 0
    assert "Referidos" in capsys.readouterr().out


def test_sin_base_avisa(tmp_path, monkeypatch):
    monkeypatch.setenv("COHORTES_DB", str(tmp_path / "no_existe.duckdb"))
    assert cli.main(["cohortes"]) == 1
