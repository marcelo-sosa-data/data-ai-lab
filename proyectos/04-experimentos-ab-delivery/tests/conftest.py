import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from experimentos.metricas import conectar  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # 52 mil usuarios: alcanza para que los efectos grandes y el SRM se vean, en ~2 s
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.35, seed=7)


@pytest.fixture(scope="session")
def con(ruta_db):
    c = conectar(ruta_db)
    yield c
    c.close()
