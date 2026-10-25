"""
El modelo incremental de eventos tiene que terminar igual que un full refresh.

Se simula un export a mitad de la matrícula 2026-2 (corte en un día X),
se construye la base, y luego se corre el build incremental con el export
completo. El resultado tiene que ser idéntico al build desde cero.
"""

import shutil
from datetime import datetime

import duckdb
import pandas as pd
import pytest

from matricula.pipeline import correr_dbt

CORTE_PARCIAL = datetime(2026, 8, 5, 12, 0)


def _fecha(txt: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(txt.strip(), fmt)
        except ValueError:
            pass
    raise ValueError(txt)


@pytest.fixture(scope="module")
def raw_parcial(raw, tmp_path_factory):
    destino = tmp_path_factory.mktemp("raw_parcial")
    for f in raw.iterdir():
        shutil.copy(f, destino / f.name)
    ev = pd.read_csv(raw / "eventos_matricula.csv", dtype=str, keep_default_na=False)
    ev[ev["fecha_hora"].map(_fecha) <= CORTE_PARCIAL].to_csv(destino / "eventos_matricula.csv", index=False)
    return destino


def _eventos(db):
    con = duckdb.connect(str(db), read_only=True)
    df = con.execute("select * from intermedio.int_eventos_limpios order by id_evento").df()
    con.close()
    return df


def test_incremental_igual_a_full_refresh(raw, raw_parcial, build, tmp_path):
    db = tmp_path / "incremental.duckdb"
    primero = correr_dbt("build", raw=raw_parcial, db=db, full_refresh=True, registrar=False)
    assert primero.exito
    n_parcial = len(_eventos(db))

    segundo = correr_dbt("build", raw=raw, db=db, registrar=False)
    assert segundo.exito
    incremental = _eventos(db)
    completo = _eventos(build[1])

    assert len(incremental) > n_parcial
    pd.testing.assert_frame_equal(incremental, completo)


def test_correr_dos_veces_no_duplica(raw, build, tmp_path):
    db = tmp_path / "doble.duckdb"
    correr_dbt("build", raw=raw, db=db, full_refresh=True, registrar=False)
    antes = len(_eventos(db))
    correr_dbt("run", raw=raw, db=db, extra=["--select", "int_eventos_limpios"], registrar=False)
    assert len(_eventos(db)) == antes
