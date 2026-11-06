"""Métricas por semana, calibración y simulación de la lista de contacto con capacidad limitada."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def metricas_semana(pred: pd.DataFrame, columnas: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """AUC-PR y AUC-ROC (sobre el puntaje que ordena) y Brier (sobre la probabilidad) por semana.

    columnas: nombre -> (columna de puntaje, columna de probabilidad)."""
    filas = []
    for w, g in pred.groupby("semana"):
        y = g.deserta.astype(int)
        for nombre, (punt, prob) in columnas.items():
            filas.append({"modelo": nombre, "semana": int(w), "alumnos": len(g), "tasa": y.mean(),
                          "auc_pr": average_precision_score(y, g[punt]), "auc_roc": roc_auc_score(y, g[punt]),
                          "brier": brier_score_loss(y, g[prob].clip(0, 1))})
    return pd.DataFrame(filas)


def calibracion(y, p, bins: int = 10) -> pd.DataFrame:
    """Riesgo promedio predicho vs tasa observada, por decil de riesgo."""
    df = pd.DataFrame({"y": np.asarray(y).astype(float), "p": np.asarray(p)})
    df["bin"] = pd.qcut(df.p.rank(method="first"), bins, labels=False)
    return df.groupby("bin").agg(p_media=("p", "mean"), tasa_obs=("y", "mean"), n=("y", "size")).reset_index()


def ece(y, p, bins: int = 10) -> float:
    """Error de calibración esperado: diferencia media ponderada entre lo predicho y lo observado."""
    c = calibracion(y, p, bins)
    return float((c.n * (c.p_media - c.tasa_obs).abs()).sum() / c.n.sum())


def simular_contactos(pred: pd.DataFrame, orden: str, capacidad: int, semanas=range(2, 17),
                      filtro: str | None = None) -> pd.DataFrame:
    """
    Cada semana w se arma la lista con los datos al cierre de w y tutoría llama durante w+1 a los
    `capacidad` primeros que todavía no contactó en el semestre. Devuelve un contacto por alumno.

    `filtro` es una columna booleana: si se da, solo entran a la lista los que la cumplen (la regla).
    """
    claves = pd.MultiIndex.from_frame(pred[["id_alumno", "periodo"]])
    codigo = pd.factorize(claves)[0]
    contactado = np.zeros(codigo.max() + 1 if len(codigo) else 0, dtype=int)   # semana de la lista, 0 = no
    sem = pred.semana.to_numpy()
    puntaje = pred[orden].to_numpy()
    ok = pred[filtro].to_numpy(bool) if filtro else np.ones(len(pred), bool)
    for w in semanas:
        i = np.flatnonzero((sem == w) & ok)
        i = i[contactado[codigo[i]] == 0]
        i = i[np.argsort(-puntaje[i], kind="stable")[:capacidad]]
        contactado[codigo[i]] = w
    primeros = pd.Series(codigo).drop_duplicates()
    out = pred.iloc[primeros.index][["id_alumno", "periodo"]].copy()
    out["semana_lista"] = contactado[primeros.to_numpy()]
    return out[out.semana_lista > 0].reset_index(drop=True)


def resumen_contactos(contactos: pd.DataFrame, desenlace: pd.DataFrame) -> dict:
    """
    desenlace: una fila por alumno-periodo con deserta y semana_abandono.
    Un desertor cuenta como alcanzado si la llamada (semana w+1) llegó antes de que dejara de ir.
    """
    d = desenlace.merge(contactos, on=["id_alumno", "periodo"], how="left")
    des = d[d.deserta == 1]
    a_tiempo = des[(des.semana_lista + 1) <= des.semana_abandono]
    contactados = d[d.semana_lista.notna()]
    return {
        "contactos": int(len(contactados)),
        "precision": float(contactados.deserta.mean()) if len(contactados) else np.nan,
        "desertores": int(len(des)),
        "alcanzados": int(len(a_tiempo)),
        "alcanzados_pct": float(len(a_tiempo) / len(des)) if len(des) else np.nan,
        "anticipacion_mediana": float((a_tiempo.semana_abandono - a_tiempo.semana_lista - 1).median())
        if len(a_tiempo) else np.nan,
    }
