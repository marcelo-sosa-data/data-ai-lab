"""
Estudio A/A: cuántos "ganadores" aparecen cuando no hay nada que ganar.

Se toman los usuarios activos de un periodo sin experimentos, se reparten al azar
en dos grupos miles de veces y se lee cada reparto como si fuera un experimento,
mirando el resultado todos los días. Con datos reales de pedidos (colas largas,
usuarios que entran a mitad de ventana) y no con normales de libro.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .catalogo import PERIODO_AA
from .estadistica import theta_cuped
from .metricas import acumulado_diario, tabla_usuarios
from .secuencial import TAU_RELATIVO, _momentos, lambda_msprt


def estudio_aa(con, repeticiones: int = 2000, seed: int = 11, alfa: float = 0.05,
               metrica: str = "pedidos", lote: int = 250) -> tuple[pd.DataFrame, dict]:
    inicio, fin = PERIODO_AA
    u = tabla_usuarios(con, "AA", inicio, fin)
    dias, acum, expo = acumulado_diario(con, "AA", u, inicio, fin, metrica)
    x = u[f"{metrica}_pre"].to_numpy(float)
    rng = np.random.default_rng(seed)
    n, d = acum.shape
    z = stats.norm.ppf(1 - alfa / 2)

    # θ de CUPED se estima con los dos grupos juntos: no depende del reparto
    ys, es = [], []
    for k in range(d):
        e = expo[:, k].astype(float)
        y = acum[:, k]
        th = theta_cuped(y[e > 0], x[e > 0]) if e.sum() > 2 else 0.0
        ys.append((y, y - th * (x - x[e > 0].mean()) if e.sum() > 2 else y))
        es.append(e)

    rechazos = {m: np.zeros((repeticiones, d), bool) for m in ("clasico", "cuped", "msprt")}
    for ini in range(0, repeticiones, lote):
        r = min(lote, repeticiones - ini)
        g = (rng.random((r, n)) < 0.5).astype(np.float64)
        for k in range(d):
            e = es[k]
            if e.sum() < 100:
                continue
            y, y_adj = ys[k]
            media_c = y[e > 0].mean()
            for nombre, yy in (("clasico", y), ("cuped", y_adj)):
                m0, m1, v0, v1 = _momentos(yy, e, g)
                zstat = (m1 - m0) / np.sqrt(v0 + v1)
                rechazos[nombre][ini:ini + r, k] = np.abs(zstat) > z
                if nombre == "cuped":
                    lam = lambda_msprt(m1 - m0, v0 + v1, (TAU_RELATIVO * media_c) ** 2)
                    rechazos["msprt"][ini:ini + r, k] = lam >= 1 / alfa

    filas = []
    for k in range(d):
        filas.append({
            "dia": k + 1,
            # si se mira todos los días hasta el día k y se para al primer p < 0.05
            "mirando_cada_dia": rechazos["cuped"][:, :k + 1].any(axis=1).mean(),
            "mirando_cada_dia_sin_cuped": rechazos["clasico"][:, :k + 1].any(axis=1).mean(),
            # una sola mirada, el día k
            "una_mirada": rechazos["cuped"][:, k].mean(),
            "msprt_cada_dia": rechazos["msprt"][:, :k + 1].any(axis=1).mean(),
        })
    curva = pd.DataFrame(filas)
    resumen = {"usuarios": n, "dias": d, "repeticiones": repeticiones, "metrica": metrica,
               "inicio": pd.Timestamp(inicio), "fin": pd.Timestamp(fin)}
    return curva, resumen
