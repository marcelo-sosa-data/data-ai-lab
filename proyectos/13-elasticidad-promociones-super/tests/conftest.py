import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from elasticidad.consultas import conectar, matrices  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # tres locales (uno por formato): mismas semanas y productos, menos filas
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.2, seed=3)


@pytest.fixture(scope="session")
def con(ruta_db):
    c = conectar(ruta_db)
    yield c
    c.close()


@pytest.fixture(scope="session")
def m(con):
    return matrices(con)


@pytest.fixture(scope="session")
def ajuste(m):
    # muestreo corto: alcanza para revisar signos y órdenes de magnitud
    from elasticidad.modelo import ajustar
    return ajustar(m, draws=150, tune=200, chains=2)
