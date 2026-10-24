import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from text2sql.db import BaseDatos  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # base chica (~3% del volumen real) para que los tests corran en segundos
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.03, seed=7)


@pytest.fixture
def db(ruta_db):
    base = BaseDatos(ruta_db, max_filas=50)
    yield base
    base.cerrar()
