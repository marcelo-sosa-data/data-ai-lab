import gzip
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "datos"))

from generar_datos import generar  # noqa: E402
from lakehouse import catalogo  # noqa: E402
from lakehouse.contrato import Contrato  # noqa: E402
from lakehouse.pipeline import correr_pendientes, preparar  # noqa: E402


@pytest.fixture(scope="session")
def contrato():
    return Contrato.desde_yaml(RAIZ / "contratos" / "envios.yml")


@pytest.fixture(scope="session")
def simulado(tmp_path_factory, contrato):
    """Diez días con el incidente del peso en gramos y un reinicio del conector, a escala chica (~15 s)."""
    d = tmp_path_factory.mktemp("sim")
    manifiesto = generar(d, escala=0.15, seed=7, desde=date(2026, 8, 15), hasta=date(2026, 8, 24))
    _, t = preparar(d / "lakehouse", contrato, d / "cdc")
    filas = correr_pendientes(t, contrato, dir_cdc=d / "cdc")
    return {"dir": d, "tablas": t, "filas": filas, "manifiesto": manifiesto}


# ------------------------------------------------------------------ eventos a mano

BASE = {
    "id_envio": 1, "codigo_seguimiento": "KL2607000001", "id_cliente": 1001, "canal": "api",
    "servicio": "express", "distrito": "Miraflores", "peso_kg": 1.2, "monto_cod": 0.0, "estado": "registrado",
    "intentos": 0, "id_courier": None, "registrado_en": "2026-08-03 10:00:00", "fecha_promesa": "2026-08-04",
    "entregado_en": None, "actualizado_en": "2026-08-03 10:00:00",
}


def fila(**cambios) -> dict:
    return {**BASE, **cambios}


def evento(lsn: int, op: str, despues: dict | None, antes: dict | None = None, ts: str | None = None) -> dict:
    img = despues or antes
    t = datetime.fromisoformat(ts or img["actualizado_en"])
    ms = int((t + timedelta(hours=5)).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return {"lsn": lsn, "op": op, "ts_ms": ms, "fuente": {}, "antes": antes, "despues": despues}


def escribir_lote(dir_cdc: Path, lote: str, eventos: list[dict]) -> None:
    carpeta = dir_cdc / f"lote={lote}"
    carpeta.mkdir(parents=True, exist_ok=True)
    with gzip.open(carpeta / "parte-0.jsonl.gz", "wt", encoding="utf-8") as fh:
        for e in eventos:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


@pytest.fixture
def vacio(tmp_path, contrato):
    """Lakehouse vacío y una carpeta CDC donde cada test escribe sus lotes."""
    # plata nace con la versión de agosto (1.0.0, sin franja_horaria)
    t = catalogo.crear_tablas(catalogo.abrir(tmp_path / "lakehouse"), contrato.vigente(date(2026, 8, 3)))
    return {"dir_cdc": tmp_path / "cdc", "tablas": t, "contrato": contrato}
