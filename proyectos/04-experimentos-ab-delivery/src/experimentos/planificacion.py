"""
Antes de lanzar: cuántos usuarios entran por semana, cuánto varía la métrica y qué
efecto se puede detectar con 1 a 4 semanas, con y sin CUPED.

Se estima con el periodo sin experimentos (el mismo del A/A), así el cálculo usa la
varianza real de los pedidos y no un supuesto.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .catalogo import PERIODO_AA
from .estadistica import mde_relativo
from .metricas import acumulado_diario, tabla_usuarios


def tabla_planificacion(con, metricas=("pedidos", "gmv"), reparto: float = 0.5) -> pd.DataFrame:
    inicio, fin = PERIODO_AA
    u = tabla_usuarios(con, "AA", inicio, fin)
    filas = []
    for met in metricas:
        dias, acum, expo = acumulado_diario(con, "AA", u, inicio, fin, met)
        x = u[f"{met}_pre"].to_numpy(float)
        for semanas in (1, 2, 3, 4):
            k = 7 * semanas - 1
            if k >= len(dias):
                continue
            e = expo[:, k]
            y = acum[e, k]
            media, sd = y.mean(), y.std(ddof=1)
            rho = float(np.corrcoef(y, x[e])[0, 1])
            n_grupo = e.sum() * min(reparto, 1 - reparto)
            filas.append({
                "metrica": met, "semanas": semanas, "usuarios": int(e.sum()), "n_por_grupo": int(n_grupo),
                "media": media, "sd": sd, "rho": rho,
                "mde_sin_cuped": mde_relativo(media, sd, n_grupo),
                "mde_con_cuped": mde_relativo(media, sd, n_grupo, rho),
            })
    return pd.DataFrame(filas)
