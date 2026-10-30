"""Etiquetas de fecha en español, armadas en Python para que el navegador no las corra de día."""

from __future__ import annotations

import pandas as pd

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def etiqueta_dia(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]}"


def etiqueta_mes(d) -> str:
    d = pd.Timestamp(d)
    return f"{MESES[d.month - 1]} {d.year}"


def rango(inicio, fin) -> str:
    """'02 mar - 29 mar 2026'."""
    fin = pd.Timestamp(fin)
    return f"{etiqueta_dia(inicio)} - {etiqueta_dia(fin)} {fin.year}"
