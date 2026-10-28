"""
Modelos de pronóstico. Todos reciben el panel con features y una fecha de corte
(lo último que se conoce) y devuelven la predicción para las filas pedidas.

- promedio_28: lo que hace hoy la cadena, el promedio de venta de las últimas 4 semanas.
- naive_estacional: la venta del mismo día de la semana, en la última semana conocida.
- lgbm: un solo LightGBM para todas las series (modelo global), objetivo Tweedie.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd

from .datos import CLAVE
from .features import COLUMNAS

PARAMETROS_LGBM = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.2,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 0,
}
RONDAS = 500
DIAS_ENTRENAMIENTO = 730  # dos años bastan; lo más antiguo no tiene lag de 364


def promedio_28(panel: pd.DataFrame, corte: pd.Timestamp, filas: pd.DataFrame) -> np.ndarray:
    """Venta promedio observada en (corte-28, corte], tal cual: incluye los días con quiebre."""
    ventana = panel[(panel.fecha > corte - pd.Timedelta(days=28)) & (panel.fecha <= corte)]
    media = ventana.groupby(CLAVE, observed=True).unidades.mean().rename("pred")
    return filas[CLAVE].merge(media.reset_index(), on=CLAVE, how="left").pred.fillna(0).to_numpy()


def naive_estacional(panel: pd.DataFrame, corte: pd.Timestamp, filas: pd.DataFrame) -> np.ndarray:
    """Para d en (corte, corte+7k] usa la venta de d-7k: el mismo día de la semana ya observado."""
    h = (filas.fecha - corte).dt.days.to_numpy()
    semanas = np.ceil(h / 7).astype(int)
    referencia = filas[CLAVE].copy()
    referencia["fecha"] = filas.fecha.to_numpy() - pd.to_timedelta(7 * semanas, unit="D")
    ventas = panel[["fecha", *CLAVE, "unidades"]]
    m = referencia.merge(ventas, on=["fecha", *CLAVE], how="left")
    return m.unidades.fillna(0).to_numpy(dtype=float)


@dataclass
class ModeloGlobal:
    """LightGBM global. `entrenar` usa solo filas con fecha <= corte y objetivo conocido."""
    rondas: int = RONDAS
    parametros: dict = field(default_factory=lambda: dict(PARAMETROS_LGBM))
    semilla: int = 42
    booster: lgb.Booster | None = None
    categorias: dict = field(default_factory=dict)

    def entrenar(self, feats: pd.DataFrame, corte: pd.Timestamp) -> "ModeloGlobal":
        desde = corte - pd.Timedelta(days=DIAS_ENTRENAMIENTO)
        m = (feats.fecha <= corte) & (feats.fecha > desde) & feats.objetivo.notna()
        datos = lgb.Dataset(feats.loc[m, COLUMNAS], label=feats.loc[m, "objetivo"],
                            categorical_feature=[c for c in COLUMNAS if str(feats[c].dtype) == "category"],
                            free_raw_data=True)
        self.categorias = {c: feats[c].cat.categories for c in COLUMNAS
                           if str(feats[c].dtype) == "category"}
        params = {**self.parametros, "seed": self.semilla}
        self.booster = lgb.train(params, datos, num_boost_round=self.rondas)
        return self

    def predecir(self, filas: pd.DataFrame) -> np.ndarray:
        if self.booster is None:
            raise RuntimeError("El modelo no está entrenado")
        x = filas[COLUMNAS].copy()
        for c, cats in self.categorias.items():  # un merge puede devolver la columna como int
            x[c] = pd.Categorical(x[c].astype(cats.dtype), categories=cats)
        return np.clip(self.booster.predict(x), 0, None)

    def importancia(self) -> pd.DataFrame:
        g = self.booster.feature_importance("gain")
        return (pd.DataFrame({"variable": self.booster.feature_name(), "ganancia": g / g.sum()})
                .sort_values("ganancia", ascending=False).reset_index(drop=True))
