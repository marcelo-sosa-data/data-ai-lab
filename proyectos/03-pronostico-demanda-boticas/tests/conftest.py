import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from demanda import backtest as bt_mod  # noqa: E402
from demanda.datos import cargar  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # 8 locales y 14 productos: la base completa toma minutos en el backtest
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.25, seed=7)


@pytest.fixture(scope="session")
def base(ruta_db):
    return cargar(ruta_db, con_latente=True)


@pytest.fixture(scope="session")
def backtest(base):
    cortes = bt_mod.cortes_por_defecto(base, n=4)
    return bt_mod.correr(base, cortes, rondas=60)
