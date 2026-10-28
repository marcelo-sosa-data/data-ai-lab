"""
Calendario comercial: feriados del Perú, quincenas y etiquetas de fecha en español.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

# Feriados nacionales (Jueves y Viernes Santo cambian cada año)
_FIJOS = ["01-01", "05-01", "06-07", "06-29", "07-23", "07-28", "07-29", "08-06", "08-30",
          "10-08", "11-01", "12-08", "12-09", "12-25"]
_SEMANA_SANTA = {2024: ("03-28", "03-29"), 2025: ("04-17", "04-18"), 2026: ("04-02", "04-03")}


def feriados(anios: range | list[int] = range(2024, 2027)) -> list[date]:
    salida = []
    for a in anios:
        dias = _FIJOS + list(_SEMANA_SANTA.get(a, ()))
        salida += [date(a, int(d[:2]), int(d[3:])) for d in dias]
    return sorted(salida)


def es_feriado(fechas: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    f = pd.DatetimeIndex(fechas)
    lista = pd.DatetimeIndex(feriados(sorted(set(f.year))))
    return np.asarray(f.normalize().isin(lista))


def es_quincena(fechas: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Días de pago: 15, 16, último día del mes y el 1."""
    f = pd.DatetimeIndex(fechas)
    return np.asarray((f.day == 15) | (f.day == 16) | f.is_month_end | (f.day == 1))


def dia_de_la_madre(anio: int) -> date:
    """Segundo domingo de mayo."""
    d = date(anio, 5, 1)
    primer_domingo = 1 + (6 - d.weekday()) % 7
    return date(anio, 5, primer_domingo + 7)


def etiqueta_mes(d) -> str:
    d = pd.Timestamp(d)
    return f"{MESES[d.month - 1]} {d.year}"


def etiqueta_dia(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]}"
