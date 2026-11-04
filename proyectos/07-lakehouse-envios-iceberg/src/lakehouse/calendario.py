"""Calendario de operación (feriados, días hábiles), lotes de 6 horas y etiquetas en español."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

# feriados nacionales que caen en el periodo simulado
FERIADOS = {date(2026, 6, 29), date(2026, 7, 23), date(2026, 7, 28), date(2026, 7, 29),
            date(2026, 8, 6), date(2026, 8, 30), date(2026, 10, 8), date(2026, 11, 1)}

HORAS_CORTE = (0, 6, 12, 18)
FORMATO_LOTE = "%Y-%m-%dT%H"


def es_habil(d: date) -> bool:
    """Se reparte de lunes a sábado, salvo feriados."""
    return d.weekday() != 6 and d not in FERIADOS


def siguiente_habil(d: date, dias: int = 1) -> date:
    """El día hábil número `dias` después de `d` (con dias=0, d o el siguiente hábil)."""
    if dias == 0:
        while not es_habil(d):
            d += timedelta(days=1)
        return d
    for _ in range(dias):
        d += timedelta(days=1)
        while not es_habil(d):
            d += timedelta(days=1)
    return d


def lote_de(ts: datetime) -> str:
    """Lote al que pertenece un commit: se nombra por la hora de corte que lo cierra.

    Los commits entre 00:00 y 05:59 salen en el lote de las 06; los de 18:00 a 23:59,
    en el de las 00 del día siguiente.
    """
    base = ts.replace(minute=0, second=0, microsecond=0)
    corte = base.replace(hour=(ts.hour // 6) * 6) + timedelta(hours=6)
    return corte.strftime(FORMATO_LOTE)


def corte_de(lote: str) -> datetime:
    return datetime.strptime(lote, FORMATO_LOTE)


def lote_siguiente(lote: str, n: int = 1) -> str:
    return (corte_de(lote) + timedelta(hours=6 * n)).strftime(FORMATO_LOTE)


def etiqueta_dia(d, con_anio: bool = False) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]}" + (f" {d.year}" if con_anio else "")


def etiqueta_corte(lote: str) -> str:
    """'2026-08-16T06' -> '16 ago 06:00'."""
    c = corte_de(lote)
    return f"{etiqueta_dia(c)} {c:%H}:00"


def etiqueta_mes(d) -> str:
    d = pd.Timestamp(d)
    return f"{MESES[d.month - 1]} {d.year}"
