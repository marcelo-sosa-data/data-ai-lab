import sys
from pathlib import Path

import duckdb
import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from reclamos.servidor import Sistemas  # noqa: E402


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # base chica (~5% del volumen) para que los tests corran en segundos
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.05, seed=7)


@pytest.fixture
def sistemas(ruta_db):
    s = Sistemas(ruta_db)
    yield s
    s.con.close()


@pytest.fixture(scope="session")
def con(ruta_db):
    c = duckdb.connect(str(ruta_db), read_only=True)
    yield c
    c.close()


def caso(con, condicion: str) -> dict:
    """Primer reclamo que cumple la condición sobre aux_verdad, con su cliente."""
    fila = con.execute(f"""
        SELECT v.*, r.id_cliente, r.texto FROM aux_verdad v JOIN reclamos r USING (id_reclamo)
        WHERE {condicion} ORDER BY id_reclamo LIMIT 1""").df()
    return fila.iloc[0].to_dict()
