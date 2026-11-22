"""
Calendario laboral de la universidad: lunes a viernes de 8:00 a 17:00, sin feriados.

Los tiempos del proceso se miden en horas hábiles porque las áreas solo
atienden en ese horario. `a_habiles` convierte una fecha a horas hábiles
acumuladas desde el origen y `a_calendario` hace lo inverso.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

HORA_APERTURA = 8
HORA_CIERRE = 17
HORAS_DIA = HORA_CIERRE - HORA_APERTURA
ORIGEN = date(2025, 12, 1)
FIN = date(2027, 12, 31)

FERIADOS = {
    date(2025, 12, 8), date(2025, 12, 9), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 4, 2), date(2026, 4, 3), date(2026, 5, 1),
    date(2026, 6, 29), date(2026, 7, 23), date(2026, 7, 28), date(2026, 7, 29),
    date(2026, 8, 6), date(2026, 8, 30), date(2026, 10, 8), date(2026, 11, 1),
    date(2026, 12, 8), date(2026, 12, 9), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 3, 25), date(2027, 3, 26),
}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def es_habil(d: date) -> bool:
    return d.weekday() < 5 and d not in FERIADOS


def _dias() -> tuple[np.ndarray, np.ndarray]:
    """Ordinal de cada día del rango y horas hábiles acumuladas al inicio de ese día."""
    n = (FIN - ORIGEN).days + 1
    dias = [ORIGEN + timedelta(days=i) for i in range(n)]
    habil = np.array([es_habil(d) for d in dias])
    acumulado = np.concatenate([[0], np.cumsum(habil * HORAS_DIA)[:-1]]).astype(float)
    return habil, acumulado


_HABIL, _ACUM = _dias()
_DIAS_HABILES = np.flatnonzero(_HABIL)  # índice (desde ORIGEN) de cada día hábil


def a_habiles(ts) -> np.ndarray | float:
    """Horas hábiles transcurridas desde ORIGEN hasta `ts` (escalar o vector)."""
    escalar = not hasattr(ts, "__len__") or isinstance(ts, str)
    t = pd.to_datetime(pd.Series([ts] if escalar else list(ts)))
    idx = (t.dt.normalize() - pd.Timestamp(ORIGEN)).dt.days.to_numpy()
    hora = (t - t.dt.normalize()).dt.total_seconds().to_numpy() / 3600
    dentro = np.clip(hora - HORA_APERTURA, 0, HORAS_DIA)
    res = _ACUM[idx] + np.where(_HABIL[idx], dentro, 0.0)
    return float(res[0]) if escalar else res


def a_calendario(h) -> pd.Timestamp | pd.DatetimeIndex:
    """Fecha y hora que corresponde a `h` horas hábiles desde ORIGEN."""
    escalar = np.isscalar(h)
    h = np.atleast_1d(np.asarray(h, dtype=float))
    k = np.minimum((h // HORAS_DIA).astype(int), len(_DIAS_HABILES) - 1)
    resto = h - k * HORAS_DIA
    dia = pd.Timestamp(ORIGEN) + pd.to_timedelta(_DIAS_HABILES[k], unit="D")
    res = dia + pd.to_timedelta(HORA_APERTURA + resto, unit="h")
    res = pd.DatetimeIndex(res).round("s")
    return res[0] if escalar else res


def dia_habil(h: float) -> tuple[date, float]:
    """Día hábil que contiene la hora hábil `h` y las horas transcurridas desde la apertura."""
    k = min(int(h // HORAS_DIA), len(_DIAS_HABILES) - 1)
    return ORIGEN + timedelta(days=int(_DIAS_HABILES[k])), h - k * HORAS_DIA


def siguiente_habil(d: date) -> date:
    while not es_habil(d):
        d += timedelta(days=1)
    return d


def dias_habiles(desde, hasta) -> np.ndarray | float:
    """Días hábiles entre dos fechas, con fracción (9 horas = 1 día)."""
    return (a_habiles(hasta) - a_habiles(desde)) / HORAS_DIA


def etiqueta_mes(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{MESES[ts.month - 1]} {ts.year}"


def etiqueta_dia(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.day} {MESES[ts.month - 1]}"


def momentos_semanales(dias_semana: list[int], hora: float, desde: datetime,
                       hasta: datetime) -> np.ndarray:
    """Horas hábiles de cada `dia_semana` a `hora` entre dos fechas (solo días hábiles)."""
    d, fin, res = desde.date() if isinstance(desde, datetime) else desde, \
        hasta.date() if isinstance(hasta, datetime) else hasta, []
    while d <= fin:
        if d.weekday() in dias_semana and es_habil(d):
            res.append(datetime(d.year, d.month, d.day) + timedelta(hours=hora))
        d += timedelta(days=1)
    return a_habiles(res) if res else np.array([])
