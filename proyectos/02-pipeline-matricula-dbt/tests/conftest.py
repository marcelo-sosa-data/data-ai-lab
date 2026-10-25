import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from matricula.consultas import Consultas  # noqa: E402
from matricula.pipeline import correr_dbt  # noqa: E402

ESCALA = 0.08   # ~8% del volumen real: el build completo corre en segundos


@pytest.fixture(scope="session")
def raw(tmp_path_factory):
    return generar(tmp_path_factory.mktemp("raw"), escala=ESCALA, seed=7)


@pytest.fixture(scope="session")
def build(raw, tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "prueba.duckdb"
    res = correr_dbt("build", raw=raw, db=db, full_refresh=True)
    os.environ["MATRICULA_RAW"] = str(raw)
    os.environ["MATRICULA_DB"] = str(db)
    return res, db


@pytest.fixture
def consultas(build):
    c = Consultas(build[1])
    yield c
    c.cerrar()
