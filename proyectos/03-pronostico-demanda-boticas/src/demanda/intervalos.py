"""
Intervalos con conformal prediction (split conformal, normalizado).

En vez de suponer una distribución, se miran los errores que el modelo ya
cometió fuera de muestra (en cortes anteriores del backtest) y se toman sus
cuantiles. El error se divide entre sqrt(pronóstico): una serie que vende 40 al
día se equivoca en más unidades que una que vende 2, y así un mismo cuantil
sirve para las dos. Se calibra por segmento de rotación.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ESCALA_MIN = 0.5


def puntaje(real, pred) -> np.ndarray:
    return (np.asarray(real, float) - np.asarray(pred, float)) / np.sqrt(np.asarray(pred, float) + ESCALA_MIN)


def _cuantil_conformal(v: np.ndarray, q: float) -> float:
    """Cuantil con la corrección de muestra finita de split conformal: ceil((n+1)q)/n."""
    n = len(v)
    if q > 0.5:
        return float(np.quantile(v, min(1.0, np.ceil((n + 1) * q) / n), method="higher"))
    return float(np.quantile(v, max(0.0, np.floor((n + 1) * q) / n), method="lower"))


@dataclass
class Calibrador:
    """Guarda cuantiles del puntaje por segmento; `aplicar` los convierte en límites."""
    cuantiles: dict[str, dict[float, float]]
    niveles: tuple[float, ...]

    @classmethod
    def ajustar(cls, real, pred, segmento, niveles=(0.1, 0.9), min_obs: int = 50) -> "Calibrador":
        s = puntaje(real, pred)
        seg = np.asarray(segmento).astype(str)
        global_q = {q: _cuantil_conformal(s, q) for q in niveles}
        cuantiles = {"_todos": global_q}
        for g in np.unique(seg):
            v = s[seg == g]
            if len(v) >= min_obs:
                cuantiles[g] = {q: _cuantil_conformal(v, q) for q in niveles}
        return cls(cuantiles, tuple(niveles))

    def aplicar(self, pred, segmento, nivel: float) -> np.ndarray:
        pred = np.asarray(pred, float)
        seg = np.asarray(segmento).astype(str)
        q = np.array([self.cuantiles.get(g, self.cuantiles["_todos"])[nivel] for g in seg])
        return np.clip(pred + q * np.sqrt(pred + ESCALA_MIN), 0, None)

    def tabla(self) -> pd.DataFrame:
        return pd.DataFrame(self.cuantiles).T.rename_axis("segmento").reset_index()
