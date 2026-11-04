"""Orquestación sin Dagster: procesa los lotes en orden, publica oro a las 06:00 y mantiene las
tablas cada domingo. Dagster (definiciones.py) llama a estas mismas funciones."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from pyiceberg.table import Table

from . import catalogo
from .bitacora import Bitacora
from .calendario import corte_de
from .cdc import lotes_disponibles
from .contrato import Contrato
from .ingesta import lotes_pendientes, procesar_lote
from .mantenimiento import estadisticas, mantener
from .oro import es_corte_oro, publicar

TABLAS_APPEND = ("bronce", "estados", "cuarentena")


def preparar(dir_lakehouse: Path | None = None, contrato: Contrato | None = None,
             dir_cdc: Path | None = None) -> tuple[Contrato, dict[str, Table]]:
    """Abre el catálogo y crea las tablas que falten. Plata nace con la versión del contrato
    vigente al primer lote; las siguientes versiones la hacen evolucionar."""
    contrato = contrato or Contrato.desde_yaml()
    lotes = lotes_disponibles(dir_cdc)
    inicial = contrato.vigente(corte_de(lotes[0]).date()) if lotes else contrato
    return contrato, catalogo.crear_tablas(catalogo.abrir(dir_lakehouse), inicial)


def es_corte_mantenimiento(lote: str) -> bool:
    c = corte_de(lote)
    return c.weekday() == 6 and c.hour == 6


def mantenimiento(t: dict[str, Table], lote: str, medir_lectura: bool = True) -> list[dict]:
    filas = []
    for nombre in ("bronce", "plata", "estados", "cuarentena", "oro"):
        leer = medir_lectura and nombre in ("bronce", "estados")
        antes = estadisticas(t[nombre], leer)
        r = mantener(t[nombre])
        despues = estadisticas(t[nombre], leer)
        fila = {"lote": lote, "tabla": nombre, **r}
        fila |= {f"antes_{k}": v for k, v in antes.fila().items() if k != "tabla"}
        fila |= {f"despues_{k}": v for k, v in despues.fila().items() if k != "tabla"}
        filas.append(fila)
    return filas


def correr(t: dict[str, Table], contrato: Contrato, lotes: list[str], con_mantenimiento: bool = True,
           bitacora: Bitacora | None = None, dir_cdc=None,
           progreso: Callable[[dict], None] | None = None) -> list[dict]:
    salida = []
    for lote in lotes:
        r = procesar_lote(t, contrato, lote, dir_cdc)
        fila = r.fila()
        fila |= {"oro_filas": 0, "seg_oro": 0.0, "seg_mantenimiento": 0.0}
        if es_corte_oro(lote) and catalogo.ultimo_lote(t["oro"]) < lote:
            t0 = time.perf_counter()
            fila["oro_filas"] = publicar(t["oro"], t["plata"], lote)
            fila["seg_oro"] = round(time.perf_counter() - t0, 3)
        if con_mantenimiento and es_corte_mantenimiento(lote):
            filas = mantenimiento(t, lote)
            fila["seg_mantenimiento"] = round(sum(f["segundos"] for f in filas), 2)
            if bitacora:
                bitacora.mantenimiento(filas)
        if bitacora:
            bitacora.lote(fila)
        if progreso:
            progreso(fila)
        salida.append(fila)
    return salida


def correr_pendientes(t, contrato, hasta: str | None = None, **kw) -> list[dict]:
    return correr(t, contrato, lotes_pendientes(t, kw.get("dir_cdc"), hasta), **kw)
