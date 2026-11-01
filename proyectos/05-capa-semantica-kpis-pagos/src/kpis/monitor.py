"""
Monitor diario de KPIs.

Para cada día se ajusta una regresión sobre los 91 días anteriores (tendencia, día de
la semana, días de pago, días previos al pago, feriados y campaña navideña) y se
compara el valor real con lo esperado. Las métricas de volumen se modelan en
logaritmo (efectos multiplicativos: un sábado es "+20%", no "+800 cobros"); las tasas,
en nivel. La escala del error sale de la MAD de los residuos, así un incidente pasado
no infla la banda. Los días ya marcados como alerta no entran al entrenamiento.

Una alerta exige las dos cosas: |z| >= 4 y un desvío mayor al umbral de negocio de
la métrica (definido en el YAML). Lo primero evita ruido; lo segundo, alertas
"significativas" que a nadie le importan.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from .calendario import es_campania_navidad, es_dia_de_pago, es_feriado
from .capa import CapaSemantica
from .compilador import Consulta

VENTANA = 91
Z_ALERTA = 4.0


@dataclass
class Configuracion:
    ventana: int = VENTANA
    z: float = Z_ALERTA
    previo_pago: bool = True  # del 10 al 14 y del 25 al 29 hay menos saldo


def es_previo_pago(fechas) -> np.ndarray:
    f = pd.DatetimeIndex(fechas)
    return np.asarray(((f.day >= 10) & (f.day <= 14)) | ((f.day >= 25) & (f.day <= 29)))


def disenio(fechas: pd.DatetimeIndex, origen: pd.Timestamp, cfg: Configuracion) -> np.ndarray:
    """Matriz de regresores para un conjunto de días."""
    cols = [np.ones(len(fechas)), (fechas - origen).days.to_numpy() / cfg.ventana]
    cols += [(fechas.dayofweek == d).astype(float) for d in range(1, 7)]
    cols += [np.asarray(es_dia_de_pago(fechas), float), np.asarray(es_feriado(fechas), float),
             np.asarray(es_campania_navidad(fechas), float)]
    if cfg.previo_pago:
        cols.append(es_previo_pago(fechas).astype(float))
    return np.column_stack(cols)


def _mad(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def _ajuste_robusto(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Mínimos cuadrados, se descartan residuos > 3 MAD y se reajusta."""
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    r = y - X @ beta
    escala = _mad(r)
    if escala > 0:
        ok = np.abs(r) <= 3 * escala
        if ok.sum() > X.shape[1] + 5:
            beta = np.linalg.lstsq(X[ok], y[ok], rcond=None)[0]
            escala = _mad((y - X @ beta)[ok])
    return beta, max(escala, 1e-9)


def vigilar_serie(serie: pd.Series, multiplicativo: bool, umbral: float,
                  cfg: Configuracion | None = None) -> pd.DataFrame:
    """Evalúa cada día de una serie diaria (índice de fechas) contra los días previos."""
    cfg = cfg or Configuracion()
    serie = serie.sort_index()
    fechas = pd.DatetimeIndex(serie.index)
    y = np.log(serie.to_numpy(float)) if multiplicativo else serie.to_numpy(float)
    alerta = np.zeros(len(y), bool)
    filas = []
    for t in range(cfg.ventana, len(y)):
        idx = np.arange(t - cfg.ventana, t)
        origen = fechas[t - cfg.ventana]
        beta, escala = _ajuste_robusto(disenio(fechas[idx], origen, cfg), y[idx])
        pred = float((disenio(fechas[t:t + 1], origen, cfg) @ beta)[0])
        z = (y[t] - pred) / escala
        if multiplicativo:
            esperado, bajo, alto = np.exp(pred), np.exp(pred - cfg.z * escala), np.exp(pred + cfg.z * escala)
            desvio = serie.iloc[t] / esperado - 1
        else:
            esperado, bajo, alto = pred, pred - cfg.z * escala, pred + cfg.z * escala
            desvio = serie.iloc[t] - esperado
        alerta[t] = abs(z) >= cfg.z and abs(desvio) >= umbral
        filas.append({"fecha": fechas[t], "valor": float(serie.iloc[t]), "esperado": float(esperado),
                      "banda_baja": float(bajo), "banda_alta": float(alto), "z": float(z),
                      "desvio": float(desvio), "alerta": bool(alerta[t])})
    return pd.DataFrame(filas)


def vigilar(capa: CapaSemantica, con: duckdb.DuckDBPyConnection,
            cfg: Configuracion | None = None) -> pd.DataFrame:
    """Corre el monitor sobre todas las métricas que tienen bloque `monitor` en el YAML."""
    metricas = {n: m for n, m in capa.definicion.metricas.items() if m.monitor}
    diario = capa.consultar(con, Consulta(metricas=list(metricas), grano="dia")).set_index("periodo")
    partes = []
    for n, m in metricas.items():
        r = vigilar_serie(diario[n], m.monitor.modelo == "multiplicativo", m.monitor.umbral_minimo, cfg)
        partes.append(r.assign(metrica=n))
    return pd.concat(partes, ignore_index=True)


def eventos(serie: pd.DataFrame) -> pd.DataFrame:
    """Agrupa días de alerta consecutivos (se tolera un día sin alerta en medio)."""
    filas = []
    for metrica, g in serie[serie.alerta].groupby("metrica"):
        g = g.sort_values("fecha")
        corte = (g.fecha.diff().dt.days > 2).cumsum()
        for _, e in g.groupby(corte):
            peor = e.loc[e.z.abs().idxmax()]
            filas.append({"metrica": metrica, "inicio": e.fecha.min(), "fin": e.fecha.max(), "dias": len(e),
                          "peor_dia": peor.fecha, "z_peor": peor.z, "desvio_peor": peor.desvio})
    cols = ["metrica", "inicio", "fin", "dias", "peor_dia", "z_peor", "desvio_peor"]
    return pd.DataFrame(filas, columns=cols).sort_values("inicio", ignore_index=True)


def evaluar(serie: pd.DataFrame, incidentes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Cruza las alertas con los incidentes reales del generador (que el monitor no leyó).
    Devuelve el detalle por incidente y las alertas que no corresponden a ninguno.
    """
    alertas = serie[serie.alerta].copy()
    alertas["incidente"] = None
    filas = []
    for inc in incidentes.itertuples():
        d0, d1 = pd.Timestamp(inc.inicio).normalize(), pd.Timestamp(inc.fin).normalize()
        dentro = alertas[(alertas.fecha >= d0) & (alertas.fecha <= d1 + pd.Timedelta(days=1))]
        alertas.loc[dentro.index, "incidente"] = inc.id_incidente
        primera = dentro.fecha.min() if len(dentro) else pd.NaT
        filas.append({"id_incidente": inc.id_incidente, "descripcion": inc.descripcion, "inicio": d0, "fin": d1,
                      "detectado": len(dentro) > 0, "primera_alerta": primera,
                      "dias_hasta_alerta": (primera - d0).days if len(dentro) else None,
                      "metricas": ", ".join(sorted(dentro.metrica.unique()))})
    return pd.DataFrame(filas), alertas[alertas.incidente.isna()].drop(columns="incidente")
