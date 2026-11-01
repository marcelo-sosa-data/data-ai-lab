import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from kpis.capa import CapaSemantica, conectar  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # un cuarto de los comercios: ~570 mil cobros, alcanza para ver los incidentes, en ~5 s
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.25, seed=7)


@pytest.fixture(scope="session")
def con(ruta_db):
    c = conectar(ruta_db)
    yield c
    c.close()


@pytest.fixture(scope="session")
def capa():
    return CapaSemantica.desde_yaml(RAIZ / "semantica" / "tinkuy.yml")
