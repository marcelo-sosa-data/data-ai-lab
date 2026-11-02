import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_corpus import generar  # noqa: E402
from reglamento.corpus import cargar_corpus  # noqa: E402
from reglamento.embeddings import CodificadorHash  # noqa: E402
from reglamento.evaluacion import cargar_preguntas  # noqa: E402
from reglamento.recuperador import Recuperador  # noqa: E402


@pytest.fixture(scope="session")
def rutas(tmp_path_factory):
    # el corpus es chico: se genera completo en milisegundos
    return generar(tmp_path_factory.mktemp("datos"), seed=7)


@pytest.fixture(scope="session")
def fragmentos(rutas):
    return cargar_corpus(rutas["corpus"])


@pytest.fixture(scope="session")
def preguntas(rutas):
    return cargar_preguntas(rutas["preguntas"])


@pytest.fixture(scope="session")
def recuperador(fragmentos):
    # vectores por trigramas: deterministas y sin descargar modelos
    return Recuperador(fragmentos, CodificadorHash())


@pytest.fixture(scope="session")
def por_id(fragmentos):
    return {f.id: f for f in fragmentos}
