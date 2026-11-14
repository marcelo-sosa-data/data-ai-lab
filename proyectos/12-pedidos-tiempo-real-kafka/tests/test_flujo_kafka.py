"""Corre el procesador de verdad contra un broker. Se salta si no hay uno.

    docker compose up -d        # Redpanda en localhost:19092
    pytest -m kafka
"""

import os
import shutil
import socket
import uuid
from dataclasses import replace

import pandas as pd
import pytest

from pedidos_rt.config import Ajustes, Topicos
from pedidos_rt.evaluacion import leer_carpeta

BROKER = os.getenv("KAFKA_BROKER", "localhost:19092")


def _hay_broker() -> bool:
    host, puerto = BROKER.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(puerto)), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [pytest.mark.kafka,
              pytest.mark.skipif(not _hay_broker(), reason=f"sin broker en {BROKER}")]


@pytest.fixture(scope="module")
def corrida(dir_datos, tmp_path_factory):
    from pedidos_rt.procesador import correr
    from pedidos_rt.productor import preparar_topicos, publicar

    sufijo = uuid.uuid4().hex[:8]
    base = tmp_path_factory.mktemp("flujo")
    aj = Ajustes(broker=BROKER, dir_estado=base / "estado", dir_salida=base,
                 topicos=Topicos(eventos=f"test.eventos.{sufijo}", minuto=f"test.minuto.{sufijo}",
                                 alertas=f"test.alertas.{sufijo}", particiones=3))
    # un solo día para que corra en segundos
    ev = pd.read_parquet(dir_datos / "eventos.parquet")
    dia = ev[ev["ts_evento"] < "2026-10-06"]
    ruta = base / "eventos_dia.parquet"
    dia.to_parquet(ruta, index=False)

    preparar_topicos(aj, reiniciar=True)
    n = publicar(aj, ruta)
    tardios = correr(replace(aj, gracia_ms=30_000), f"test-{sufijo}", base / "salida", espera_s=5)
    yield {"base": base / "salida", "eventos": dia, "publicados": n, "tardios": tardios}
    shutil.rmtree(base, ignore_errors=True)


def test_publica_todo(corrida):
    assert corrida["publicados"] == len(corrida["eventos"])


def test_dedup_y_conciliacion(corrida):
    ev = corrida["eventos"]
    unicos = ev[~ev["es_reintento"]]
    minutos = leer_carpeta(corrida["base"] / "minutos")
    tardios = leer_carpeta(corrida["base"] / "tardios")
    assert corrida["tardios"] == len(tardios) > 0
    for tipo, col in (("creado", "creados"), ("asignado", "asignados")):
        en_vivo = minutos[col].sum()
        tard = (tardios["tipo"] == tipo).sum()
        # las últimas ventanas del día quedan abiertas al terminar la repetición
        assert en_vivo + tard <= (unicos["tipo"] == tipo).sum()
        assert en_vivo + tard >= 0.97 * (unicos["tipo"] == tipo).sum()
    assert not tardios["evento_id"].duplicated().any()


def test_ventanas_se_emiten_despues_de_la_gracia(corrida):
    minutos = leer_carpeta(corrida["base"] / "minutos")
    assert (minutos["emitido_ms"] >= minutos["fin_ms"] + 30_000).all()
    assert not minutos.duplicated(["zona", "inicio_ms"]).any()


def test_cola_y_alertas(corrida):
    cola = leer_carpeta(corrida["base"] / "cola")
    assert cola["inicio_ms"].mod(60_000).eq(0).all()
    assert (cola["emitido_ms"] >= cola["inicio_ms"]).all()
    alertas = leer_carpeta(corrida["base"] / "alertas")
    if len(alertas):
        assert set(alertas["accion"]) <= {"abrir", "cerrar"}
        assert (alertas.loc[alertas["accion"] == "abrir", "sin_motorizado"] >= 7).all()
