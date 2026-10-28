"""Métricas de error. Todas agregan en unidades: una serie que vende 50 al día pesa más que una que vende 1."""

from __future__ import annotations

import numpy as np
import pandas as pd


def wape(real, pred) -> float:
    """Error absoluto total / venta total. 0.30 = me equivoco en 30% de las unidades."""
    real, pred = np.asarray(real, float), np.asarray(pred, float)
    total = real.sum()
    return float(np.abs(pred - real).sum() / total) if total else float("nan")


def sesgo(real, pred) -> float:
    """(pronóstico - real) / real. Negativo = el modelo se queda corto."""
    real, pred = np.asarray(real, float), np.asarray(pred, float)
    total = real.sum()
    return float((pred - real).sum() / total) if total else float("nan")


def cobertura(real, inferior, superior) -> float:
    """Fracción de valores reales que cae dentro del intervalo."""
    real = np.asarray(real, float)
    return float(np.mean((real >= np.asarray(inferior)) & (real <= np.asarray(superior))))


def resumen(df: pd.DataFrame, real: str, pred: str, por: list[str] | None = None) -> pd.DataFrame:
    """WAPE, sesgo y unidades, total o por grupo."""
    def _f(g):
        return pd.Series({"wape": wape(g[real], g[pred]), "sesgo": sesgo(g[real], g[pred]),
                          "unidades": g[real].sum(), "filas": len(g)})
    if not por:
        return _f(df).to_frame().T
    return df.groupby(por, observed=True)[[real, pred]].apply(_f).reset_index()
