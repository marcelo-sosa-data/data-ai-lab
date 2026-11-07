"""
BG/NBD, su variante modificada (MBG/NBD) y Gamma-Gamma con pymc-marketing.

El BG/NBD clásico supone que nadie abandona antes de su primera compra
repetida, así que a un cliente con una sola compra le da P(vivo) = 1 aunque
lleve meses sin aparecer. El MBG/NBD permite el abandono desde el primer día
y es el que se usa para el LTV; el clásico queda para la comparación.

El modelo de compras lleva el canal de adquisición como covariable de la tasa de compra
y de la probabilidad de abandono (Orgánico es la base). El Gamma-Gamma se
ajusta por separado en cada canal, porque el ticket cambia mucho entre canales
y un solo modelo jala a todos hacia el promedio.

Por defecto se ajusta por MAP: con ~50 mil clientes tarda segundos y el
punto estimado alcanza para comparar canales. Con `metodo="mcmc"` se obtiene
la posterior completa, a costa de varios minutos.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import warnings

import numpy as np
import pandas as pd
from pymc_marketing import clv

BASE = "Orgánico"
COLUMNAS_RFM = ["customer_id", "frequency", "recency", "T"]

logging.getLogger("pymc").setLevel(logging.ERROR)
logging.getLogger("pymc_marketing").setLevel(logging.ERROR)


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "canal_" + re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def columnas_canal(canales: list[str]) -> dict[str, str]:
    """Nombre de la columna dummy de cada canal (sin la base)."""
    return {c: _slug(c) for c in canales if c != BASE}


def con_dummies(df: pd.DataFrame, canales: list[str]) -> pd.DataFrame:
    out = df.copy()
    for canal, col in columnas_canal(canales).items():
        out[col] = (out.canal == canal).astype(float)
    return out


def _escalar(x) -> np.ndarray:
    """Quita las dimensiones chain/draw de un MAP y devuelve un vector."""
    x = x.squeeze()
    for d in ("chain", "draw"):
        if d in x.dims:
            x = x.mean(d)
    return np.asarray(x)


class ModeloCompras:
    """BG/NBD (o MBG/NBD si `modificado`) con o sin el canal como covariable."""

    def __init__(self, canales: list[str], con_canal: bool = True, modificado: bool = False):
        self.canales = list(canales)
        self.con_canal = con_canal
        self.modificado = modificado
        self.cols = list(columnas_canal(self.canales).values()) if con_canal else []
        self.modelo: clv.BetaGeoModel | clv.ModifiedBetaGeoModel | None = None

    def _datos(self, df: pd.DataFrame) -> pd.DataFrame:
        d = con_dummies(df, self.canales) if self.con_canal else df
        return d[COLUMNAS_RFM + self.cols].reset_index(drop=True)

    def ajustar(self, rfm: pd.DataFrame, metodo: str = "map", seed: int = 7, **kw) -> "ModeloCompras":
        cfg = {"purchase_covariate_cols": self.cols, "dropout_covariate_cols": self.cols}
        clase = clv.ModifiedBetaGeoModel if self.modificado else clv.BetaGeoModel
        self.modelo = clase(model_config=cfg, sampler_config=kw or None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.modelo.fit(data=self._datos(rfm), method=metodo, progressbar=False, random_seed=seed)
        return self

    def compras_esperadas(self, rfm: pd.DataFrame, dias: int) -> np.ndarray:
        """Compras repetidas esperadas de cada cliente en los próximos `dias`."""
        return _escalar(self.modelo.expected_purchases(data=self._datos(rfm), future_t=dias))

    def prob_vivo(self, rfm: pd.DataFrame) -> np.ndarray:
        return _escalar(self.modelo.expected_probability_alive(data=self._datos(rfm)))

    def nuevo_cliente(self, dias: list[int] | np.ndarray) -> pd.DataFrame:
        """Compras repetidas esperadas de un cliente nuevo de cada canal a t días de su primera compra."""
        filas = []
        for canal in self.canales:
            d = pd.DataFrame({"customer_id": [0], "canal": [canal], "frequency": [0.0],
                              "recency": [0.0], "T": [1.0]})
            d = self._datos(d)
            for t in dias:
                v = _escalar(self.modelo.expected_purchases_new_customer(data=d, t=int(t)))
                filas.append({"canal": canal, "dias": int(t), "compras": float(np.ravel(v)[0])})
        return pd.DataFrame(filas)

    def parametros(self) -> pd.DataFrame:
        """Coeficientes del canal sobre la tasa de compra y sobre el abandono."""
        s = self.modelo.fit_summary()
        if isinstance(s, pd.DataFrame):
            s = s["mean"]
        s = s[[i for i in s.index if not re.search(r"\[\d+\]$", i)]]
        return s.rename("valor").reset_index().rename(columns={"index": "parametro"})


class ModeloGasto:
    """Gamma-Gamma por canal sobre el ingreso promedio de los días repetidos."""

    def __init__(self):
        self.modelos: dict[str, clv.GammaGammaModel] = {}

    @staticmethod
    def _apto(df: pd.DataFrame) -> pd.DataFrame:
        d = df[(df.frequency > 0) & (df.monetary_value > 0)]
        return d[["customer_id", "monetary_value", "frequency"]].reset_index(drop=True)

    def ajustar(self, rfm: pd.DataFrame, seed: int = 7) -> "ModeloGasto":
        for canal, d in rfm.groupby("canal"):
            m = clv.GammaGammaModel()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.fit(data=self._apto(d), method="map", progressbar=False, random_seed=seed)
            self.modelos[canal] = m
        return self

    def gasto_esperado(self, rfm: pd.DataFrame) -> np.ndarray:
        """Ingreso esperado por compra de cada cliente (con frecuencia 0 vuelve a la media del canal)."""
        out = np.empty(len(rfm))
        rfm = rfm.reset_index(drop=True)
        for canal, d in rfm.groupby("canal"):
            x = d[["customer_id", "monetary_value", "frequency"]].copy()
            out[d.index] = _escalar(self.modelos[canal].expected_customer_spend(data=x))
        return out

    def gasto_nuevo(self) -> dict[str, float]:
        """Ingreso esperado por compra de un cliente nuevo de cada canal."""
        return {c: float(np.ravel(_escalar(m.expected_new_customer_spend()))[0]) for c, m in self.modelos.items()}


def tasa_historica(rfm: pd.DataFrame, dias: int) -> np.ndarray:
    """Referencia ingenua: el ritmo de compra observado se mantiene, nadie se va."""
    return (rfm.frequency / rfm["T"].clip(lower=1) * dias).to_numpy()
