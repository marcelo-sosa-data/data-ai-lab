"""Calendario peruano (feriados, días de pago) y etiquetas de fecha en español."""

from __future__ import annotations

import pandas as pd

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

FERIADOS = pd.to_datetime([
    "2025-07-23", "2025-07-28", "2025-07-29", "2025-08-06", "2025-08-30", "2025-10-08",
    "2025-11-01", "2025-12-08", "2025-12-09", "2025-12-25",
    "2026-01-01", "2026-04-02", "2026-04-03", "2026-05-01", "2026-06-07", "2026-06-29",
    "2026-07-23", "2026-07-28", "2026-07-29", "2026-08-06", "2026-08-30",
])


def es_feriado(fechas) -> pd.Series | bool:
    return pd.DatetimeIndex(pd.to_datetime(fechas)).isin(FERIADOS)


def es_dia_de_pago(fechas):
    """Quincena y fin de mes: días 1, 15, 16 y el último de cada mes."""
    f = pd.DatetimeIndex(pd.to_datetime(fechas))
    return ((f.day == 1) | (f.day == 15) | (f.day == 16) | f.is_month_end)


def es_campania_navidad(fechas):
    f = pd.DatetimeIndex(pd.to_datetime(fechas))
    return (f.month == 12) & (f.day >= 15) & (f.day <= 24)


def etiqueta_dia(d, con_anio: bool = False) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]}" + (f" {d.year}" if con_anio else "")


def etiqueta_mes(d) -> str:
    d = pd.Timestamp(d)
    return f"{MESES[d.month - 1]} {d.year}"


def etiqueta_periodo(d, grano: str | None) -> str:
    """Etiqueta para el eje X según el grano de la consulta."""
    d = pd.Timestamp(d)
    if grano == "mes":
        return etiqueta_mes(d)
    if grano == "trimestre":
        return f"T{(d.month - 1) // 3 + 1} {d.year}"
    if grano == "anio":
        return str(d.year)
    return etiqueta_dia(d, con_anio=True)
