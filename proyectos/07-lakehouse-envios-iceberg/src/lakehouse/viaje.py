"""Viaje en el tiempo sobre oro: qué decía el tablero cada mañana y cuánto cambió después."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pyiceberg.expressions import EqualTo
from pyiceberg.table import Table

from .oro import cortes, indicadores


def tablero_al_corte(oro: Table, dia: date) -> pd.DataFrame:
    """La tabla oro tal como estaba en el corte de las 06:00 de `dia`."""
    snaps = cortes(oro)
    if dia not in snaps:
        raise KeyError(f"no hay corte etiquetado para {dia}")
    return oro.scan(snapshot_id=snaps[dia]).to_pandas()


def promesa_por_corte(oro: Table, fecha_promesa: date, por: list[str] | None = None) -> pd.DataFrame:
    """Indicadores de una fecha de promesa vistos desde cada corte posterior."""
    filas = []
    for dia, sid in sorted(cortes(oro).items()):
        if dia <= fecha_promesa:
            continue
        df = oro.scan(snapshot_id=sid, row_filter=EqualTo("fecha_promesa", fecha_promesa.isoformat())).to_pandas()
        if df.empty:
            continue
        g = indicadores(df, por or ["fecha_promesa"])
        g.insert(0, "corte", dia)
        filas.append(g)
    return pd.concat(filas, ignore_index=True) if filas else pd.DataFrame()


def todos_los_cortes(oro: Table) -> pd.DataFrame:
    """Todas las filas de todos los cortes, con la fecha del corte desde el que se ven."""
    partes = []
    for dia, sid in sorted(cortes(oro).items()):
        df = oro.scan(snapshot_id=sid).to_pandas()
        df.insert(0, "dia_corte", dia)
        partes.append(df)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def reportado_vs_final(historial: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """OTD de cada promesa en el primer corte (la mañana siguiente) contra el último corte."""
    por = por or []
    h = historial.copy()
    h["dia_corte"] = pd.to_datetime(h["dia_corte"])
    h["fecha_promesa"] = pd.to_datetime(h["fecha_promesa"])
    primero = h.groupby("fecha_promesa")["dia_corte"].transform("min")
    ultimo = h.groupby("fecha_promesa")["dia_corte"].transform("max")
    claves = ["fecha_promesa", *por]
    a = indicadores(h[h["dia_corte"] == primero], claves)
    b = indicadores(h[h["dia_corte"] == ultimo], claves)
    a = a.rename(columns=lambda c: c if c in claves else f"{c}_reportado")
    b = b.rename(columns=lambda c: c if c in claves else f"{c}_final")
    m = a.merge(b, on=claves)
    m["brecha_pp"] = (m["otd_final"] - m["otd_reportado"]) * 100
    return m
