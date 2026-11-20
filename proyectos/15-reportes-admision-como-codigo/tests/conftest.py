import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from admision.lectura import leer_todo  # noqa: E402
from admision.modelo import construir  # noqa: E402
from generar_datos import generar  # noqa: E402


@pytest.fixture(scope="session")
def carpeta(tmp_path_factory):
    # la mitad del volumen: alcanza para que las incidencias tengan filas que tocar
    return generar(tmp_path_factory.mktemp("datos"), escala=0.5, seed=7)


@pytest.fixture(scope="session")
def lectura(carpeta):
    return leer_todo(carpeta / "crudo")


@pytest.fixture(scope="session")
def con(lectura):
    c = construir(lectura)
    yield c
    c.close()
