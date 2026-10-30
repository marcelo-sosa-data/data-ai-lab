"""
Lectura secuencial con mSPRT (mixture Sequential Probability Ratio Test).

Mirar el p-valor clásico todos los días y parar cuando baja de 0.05 infla los falsos
positivos: el test asume una sola mirada. El mSPRT con mezcla normal N(0, τ²) da un
p-valor "siempre válido": se puede revisar cada mañana y parar cuando cruza el
umbral sin pasarse del 5% de error tipo I (Johari et al., 2017).

    Λ = sqrt(V / (V + τ²)) · exp(τ² Δ² / (2 V (V + τ²)))      se rechaza si Λ ≥ 1/α

Δ es la diferencia observada y V su varianza. τ fija dónde el test tiene más
potencia; se usa un efecto del orden del que se espera (aquí 5% de la media).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .estadistica import theta_cuped

TAU_RELATIVO = 0.05


def lambda_msprt(dif, var, tau2):
    dif, var = np.asarray(dif, float), np.asarray(var, float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        log_l = 0.5 * np.log(var / (var + tau2)) + tau2 * dif**2 / (2 * var * (var + tau2))
    return np.where(var > 0, np.exp(np.minimum(log_l, 700)), 1.0)


def semiancho_msprt(var, tau2, alfa=0.05):
    """Semiancho del intervalo siempre válido: {θ : Λ(θ) < 1/α}."""
    var = np.asarray(var, float)
    return np.sqrt(var * (var + tau2) / tau2 * (np.log((var + tau2) / var) - 2 * np.log(alfa)))


def _momentos(y, e, g):
    """Medias y varianzas de la media por grupo, a la vez para muchas asignaciones (filas de g)."""
    ye = y * e
    n1 = g @ e
    s1 = g @ ye
    q1 = g @ (ye * y)
    n0 = e.sum() - n1
    s0 = ye.sum() - s1
    q0 = (ye * y).sum() - q1
    with np.errstate(divide="ignore", invalid="ignore"):
        m1, m0 = s1 / n1, s0 / n0
        v1 = (q1 / n1 - m1**2) * n1 / (n1 - 1) / n1
        v0 = (q0 / n0 - m0**2) * n0 / (n0 - 1) / n0
    return m0, m1, v0, v1


def trayectoria(dias, acumulado, expuesto, t, x=None, alfa=0.05, tau_rel=TAU_RELATIVO) -> pd.DataFrame:
    """
    Lo que se habría visto cada día de la ventana: efecto, p-valor clásico y p-valor
    siempre válido. Si se pasa la covariable `x`, cada día se ajusta con CUPED.
    """
    t = np.asarray(t, bool)
    g = t.astype(float)[None, :]
    filas = []
    # el intervalo no se intersecta entre días: si el efecto cambia (novedad), el estimando también
    p_sv = 1.0
    for k, dia in enumerate(dias):
        e = expuesto[:, k].astype(float)
        y = acumulado[:, k].astype(float)
        if x is not None and e.sum() > 2:
            m = e > 0
            th = theta_cuped(y[m], x[m])
            y = y - th * (x - x[m].mean())
        m0, m1, v0, v1 = (a[0] for a in _momentos(y, e, g))
        n1 = int((e * t).sum())
        n0 = int(e.sum()) - n1
        if min(n0, n1) < 30:
            continue
        media_c = acumulado[(e > 0) & ~t, k].mean()
        dif, var = m1 - m0, v0 + v1
        tau2 = (tau_rel * media_c) ** 2
        lam = float(lambda_msprt(dif, var, tau2))
        p_sv = min(p_sv, 1 / lam)
        h = float(semiancho_msprt(var, tau2, alfa))
        z = stats.norm.ppf(1 - alfa / 2)
        filas.append({
            "fecha": dia, "dia": k + 1, "n_control": n0, "n_tratamiento": n1,
            "relativo": dif / media_c, "ic_bajo": (dif - z * np.sqrt(var)) / media_c,
            "ic_alto": (dif + z * np.sqrt(var)) / media_c,
            "p_clasico": float(2 * stats.norm.sf(abs(dif) / np.sqrt(var))),
            "p_siempre_valido": p_sv,
            "sv_bajo": (dif - h) / media_c, "sv_alto": (dif + h) / media_c,
        })
    return pd.DataFrame(filas)
