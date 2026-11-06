"""Modelo de riesgo (LightGBM), regresión logística de referencia, regla actual y calibración."""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .features import CATEGORICAS, COLUMNAS

PARAMETROS = dict(learning_rate=0.05, num_leaves=15, min_child_samples=500, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.7, reg_lambda=5.0)
UMBRAL_ASISTENCIA = 0.70
NOTA_APROBATORIA = 10.5


def entrenar_lgbm(df: pd.DataFrame, rondas: int = 600, seed: int = 7) -> lgb.LGBMClassifier:
    """Un solo modelo para todas las semanas: la semana entra como variable."""
    m = lgb.LGBMClassifier(n_estimators=rondas, random_state=seed, verbose=-1, n_jobs=-1, **PARAMETROS)
    m.fit(df[COLUMNAS], df.deserta.astype(int), categorical_feature=CATEGORICAS)
    return m


def entrenar_logistica(df: pd.DataFrame):
    """Referencia lineal con las mismas variables: mediana + indicador de faltante, escalado y one-hot."""
    numericas = [c for c in COLUMNAS if c not in CATEGORICAS]
    prep = ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), numericas),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAS),
    ])
    m = make_pipeline(prep, LogisticRegression(max_iter=1000, C=1.0))
    X = df[COLUMNAS].copy()
    for c in CATEGORICAS:
        X[c] = X[c].astype(str)
    m.fit(X, df.deserta.astype(int))
    return m


def predecir(modelo, df: pd.DataFrame) -> np.ndarray:
    X = df[COLUMNAS]
    if not isinstance(modelo, lgb.LGBMClassifier):
        X = X.copy()
        for c in CATEGORICAS:
            X[c] = X[c].astype(str)
    return modelo.predict_proba(X)[:, 1]


class Calibrador:
    """Isotónica ajustada en un semestre que el modelo no vio. Devuelve probabilidades que se pueden leer
    como 'de cada 100 alumnos con este riesgo, tantos no vuelven'."""

    def __init__(self):
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def ajustar(self, p: np.ndarray, y: np.ndarray) -> "Calibrador":
        self.iso.fit(np.asarray(p), np.asarray(y).astype(float))
        return self

    def __call__(self, p: np.ndarray) -> np.ndarray:
        return self.iso.predict(np.asarray(p))


def alertas_regla(df: pd.DataFrame) -> pd.DataFrame:
    """La regla que usa hoy Bienestar: tres alertas independientes, cada una con su umbral."""
    notas = df[["nota_pc1", "nota_parcial", "nota_pc2"]]
    return pd.DataFrame({
        "asistencia": df.asistencia_acum < UMBRAL_ASISTENCIA,
        "evaluacion_desaprobada": notas.lt(NOTA_APROBATORIA).any(axis=1),
        "deuda": df.cuotas_vencidas >= 2,
    }, index=df.index)


def regla_actual(df: pd.DataFrame) -> pd.Series:
    return alertas_regla(df).any(axis=1)


def orden_regla(df: pd.DataFrame) -> pd.Series:
    """La regla con un orden razonable: primero más alertas, después menor asistencia."""
    return alertas_regla(df).sum(axis=1) * 10 - df.asistencia_acum.fillna(1)
