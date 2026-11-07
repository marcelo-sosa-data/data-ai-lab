import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from cohortes.consultas import conectar  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # ~12% del volumen real: alcanza para los patrones y los modelos ajustan en segundos
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.12, seed=3)


@pytest.fixture(scope="session")
def con(ruta_db):
    c = conectar(ruta_db)
    yield c
    c.close()
