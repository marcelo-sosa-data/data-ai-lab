import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from tramites.lectura import leer  # noqa: E402
from tramites.tiempos import tiempos_evento  # noqa: E402


@pytest.fixture(scope="session")
def carpeta(tmp_path_factory):
    # base chica (15% del volumen) para que los tests corran en segundos
    destino = tmp_path_factory.mktemp("datos")
    generar(destino, escala=0.15, seed=5)
    return destino


@pytest.fixture(scope="session")
def log(carpeta):
    return leer(carpeta / "exports")


@pytest.fixture(scope="session")
def ev_t(log):
    return tiempos_evento(log.eventos)
