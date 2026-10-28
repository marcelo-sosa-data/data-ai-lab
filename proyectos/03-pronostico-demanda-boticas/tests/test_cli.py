import duckdb
import pytest

from demanda.cli import main


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTICAS_DB", str(tmp_path / "b.duckdb"))
    monkeypatch.setenv("BOTICAS_RESULTADOS", str(tmp_path / "r.duckdb"))
    return tmp_path


def test_flujo_completo(entorno):
    assert main(["generar", "--escala", "0.25", "--seed", "3"]) == 0
    assert main(["backtest", "--cortes", "3", "--rondas", "30"]) == 0
    assert main(["reposicion"]) == 0
    assert main(["pronostico", "--local", "2", "--rondas", "30"]) == 0
    con = duckdb.connect(str(entorno / "r.duckdb"), read_only=True)
    tablas = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    n_pron, horizonte = con.execute("SELECT COUNT(*), MAX(horizonte) FROM pronostico").fetchone()
    pedidos_neg = con.execute("SELECT COUNT(*) FROM pedido_sugerido WHERE pedido < 0").fetchone()[0]
    con.close()
    assert {"predicciones", "metricas_modelos", "simulacion_resumen", "pedido_sugerido"} <= tablas
    assert n_pron > 0 and horizonte == 14
    assert pedidos_neg == 0


def test_sin_datos_avisa(entorno, capsys):
    assert main(["reposicion"]) == 1
    assert "generar" in capsys.readouterr().out
