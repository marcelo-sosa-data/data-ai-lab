import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402


@pytest.fixture(scope="session")
def dir_datos(tmp_path_factory):
    # 15% del volumen: alcanza para que haya colas en los incidentes y corre en ~1 s
    d = tmp_path_factory.mktemp("datos")
    generar(d, escala=0.15, seed=11)
    return d
