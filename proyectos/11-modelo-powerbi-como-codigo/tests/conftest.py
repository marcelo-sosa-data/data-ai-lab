import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from semantico.motor import Motor  # noqa: E402
from semantico.pruebas import cargar_casos, conexion_sql  # noqa: E402
from semantico.tmdl import cargar_modelo  # noqa: E402

CARPETA_MODELO = RAIZ / "modelo" / "Matricula.SemanticModel"


@pytest.fixture(scope="session")
def carpeta_datos(tmp_path_factory):
    # un décimo del volumen para que los tests corran en segundos
    return generar(tmp_path_factory.mktemp("parquet"), escala=0.1, seed=3)


@pytest.fixture(scope="session")
def modelo():
    return cargar_modelo(CARPETA_MODELO)


@pytest.fixture(scope="session")
def motor(modelo, carpeta_datos):
    return Motor.desde_carpeta(modelo, carpeta_datos)


@pytest.fixture(scope="session")
def casos():
    return cargar_casos(RAIZ / "pruebas_dax" / "casos.yaml")


@pytest.fixture(scope="session")
def con(carpeta_datos):
    return conexion_sql(carpeta_datos)
