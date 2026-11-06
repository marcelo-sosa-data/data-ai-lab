import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from desercion.datos import cargar  # noqa: E402
from desercion.features import panel  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # ~15% de los alumnos: alcanza para todos los patrones y entrena en segundos
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.15, seed=3)


@pytest.fixture(scope="session")
def base(ruta_db):
    return cargar(ruta_db, con_causas=True)


@pytest.fixture(scope="session")
def pnl(base):
    return panel(base)
