import gzip
import json
from collections import defaultdict
from datetime import date

import pandas as pd

from generar_datos import generar
from lakehouse.calendario import lote_de, siguiente_habil
from lakehouse.cdc import leer_lote, lotes_disponibles


def test_reproducible(tmp_path):
    a = generar(tmp_path / "a", escala=0.03, seed=3, desde=date(2026, 8, 17), hasta=date(2026, 8, 19))
    b = generar(tmp_path / "b", escala=0.03, seed=3, desde=date(2026, 8, 17), hasta=date(2026, 8, 19))
    assert a == b
    pa_ = pd.read_parquet(tmp_path / "a" / "origen" / "envios.parquet")
    pb = pd.read_parquet(tmp_path / "b" / "origen" / "envios.parquet")
    pd.testing.assert_frame_equal(pa_, pb)


def test_eventos_coherentes(simulado):
    d = simulado["dir"] / "cdc"
    por_envio = defaultdict(list)
    for lote in lotes_disponibles(d):
        for e in leer_lote(lote, d).to_pylist():
            por_envio[e["id_envio"]].append(e)
    for evs in list(por_envio.values())[:2000]:
        unicos = {e["lsn"]: e for e in evs}
        ordenados = [unicos[k] for k in sorted(unicos)]
        assert ordenados[0]["op"] == "c"
        assert all(x["ts_commit"] <= y["ts_commit"] for x, y in zip(ordenados, ordenados[1:]))
        # el antes de cada update es el después del evento anterior
        for x, y in zip(ordenados, ordenados[1:]):
            if y["op"] == "u":
                assert json.loads(y["antes"]) == json.loads(x["despues"])
    # ningún evento llega antes de su lote
    for lote in lotes_disponibles(d)[:10]:
        assert all(lote_de(e["ts_commit"]) <= lote for e in leer_lote(lote, d).to_pylist())


def test_incidentes_inyectados(simulado):
    m = simulado["manifiesto"]
    assert m["peso_en_gramos"] and m["eventos_duplicados"] > 0 and m["eventos_tarde"] > 0
    assert any(r["lote"] == "2026-08-19T18" for r in m["reinicios"])
    origen = pd.read_parquet(simulado["dir"] / "origen" / "envios.parquet")
    assert (origen["peso_kg"] <= 70).all()  # el script de origen corrigió los gramos
    assert not origen["id_envio"].isin(m["borrados"]).any()


def test_ts_ms_en_utc(simulado):
    archivo = sorted((simulado["dir"] / "cdc").glob("lote=2026-08-17T12/*.gz"))[0]
    e = json.loads(gzip.open(archivo, "rt").readline())
    local = pd.Timestamp((e["despues"] or e["antes"])["actualizado_en"])
    assert pd.Timestamp(e["ts_ms"], unit="ms").floor("s") - local == pd.Timedelta(hours=5)


def test_calendario():
    assert lote_de(pd.Timestamp("2026-08-03 05:59:59").to_pydatetime()) == "2026-08-03T06"
    assert lote_de(pd.Timestamp("2026-08-03 23:10:00").to_pydatetime()) == "2026-08-04T00"
    assert siguiente_habil(date(2026, 8, 29)) == date(2026, 8, 31)  # sábado -> domingo 30 y feriado
    assert siguiente_habil(date(2026, 8, 5)) == date(2026, 8, 7)    # 6 de agosto es feriado
