import shutil
import sys
from pathlib import Path

import duckdb
import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402

HAY_TESSERACT = shutil.which("tesseract") is not None


@pytest.fixture(scope="session")
def ruta_db(tmp_path_factory):
    # ~8% del volumen: unos 80 comprobantes con sus imágenes, en segundos
    return generar(tmp_path_factory.mktemp("datos") / "prueba.duckdb", escala=0.08, seed=7)


@pytest.fixture(scope="session")
def tablas(ruta_db):
    con = duckdb.connect(str(ruta_db), read_only=True)
    datos = {t: con.execute(f"SELECT * FROM {t}").df()
             for t in ["aux_verdad", "recepcion", "padron", "ordenes_compra", "empresa"]}
    con.close()
    return datos


@pytest.fixture
def ctx(ruta_db):
    from comprobantes.procesar import cargar_contexto

    con = duckdb.connect(str(ruta_db), read_only=True)
    c = cargar_contexto(con)
    con.close()
    return c
