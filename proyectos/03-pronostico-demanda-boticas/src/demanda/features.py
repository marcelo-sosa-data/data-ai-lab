"""
Variables para el modelo global.

Todas las variables de venta usan información de 14 días atrás o más. Así una
sola tabla de features sirve para pronosticar cualquier día de las próximas dos
semanas sin filtrar el futuro: para el día d solo se mira hasta d-14. Lo que sí
se conoce de antemano (calendario, feriados, promociones planificadas) entra
con la fecha del día a pronosticar.

Quiebres: un día con stock_cierre = 0 se vendió lo que había, no lo que se
pidió. Con `tratar_quiebres=True` esos días se tratan como dato faltante en los
promedios y rezagos (en vez de contar como venta baja) y no se usan como
objetivo al entrenar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .calendario import es_feriado, es_quincena
from .datos import CLAVE

REZAGO_MIN = 14
CATEGORICAS = ["id_local", "id_producto", "categoria", "region", "formato"]


def _posicion(panel: pd.DataFrame) -> np.ndarray:
    """Índice del día dentro de su serie (0 = primer día de la serie)."""
    return panel.groupby(CLAVE, sort=False).cumcount().to_numpy()


def media_rezagada(x: np.ndarray, pos: np.ndarray, desde: int, hasta: int, min_n: int = 1) -> np.ndarray:
    """
    Promedio de x entre t-hasta y t-desde (ambos incluidos) dentro de la misma serie,
    ignorando NaN. El panel debe venir ordenado por serie y fecha, sin huecos.
    """
    n = len(x)
    valido = ~np.isnan(x)
    suma = np.concatenate([[0.0], np.cumsum(np.where(valido, x, 0.0))])
    cuenta = np.concatenate([[0], np.cumsum(valido)])
    t = np.arange(n)
    fin = t - desde
    ini = np.maximum(t - hasta, t - pos)  # no cruzar al inicio de la serie
    ok = pos >= desde
    fin_c = np.clip(fin, -1, n - 1) + 1
    ini_c = np.clip(ini, 0, n - 1)
    s = np.where(ok, suma[fin_c] - suma[ini_c], np.nan)
    c = np.where(ok, cuenta[fin_c] - cuenta[ini_c], 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(c >= min_n, s / np.maximum(c, 1), np.nan)


def rezago(x: np.ndarray, pos: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    out[pos < k] = np.nan
    return out


def construir(panel: pd.DataFrame, tratar_quiebres: bool = True) -> pd.DataFrame:
    """Devuelve el panel con las columnas de features y `objetivo` (NaN donde no se entrena)."""
    df = panel.copy()
    pos = _posicion(df)
    y = df.unidades.to_numpy(dtype=float)  # NaN en días futuros
    quiebre = df.quiebre.to_numpy()
    y_aj = np.where(quiebre, np.nan, y) if tratar_quiebres else y

    for k in (14, 21, 28, 35, 364):
        df[f"lag_{k}"] = rezago(y_aj, pos, k)
    df["media_7"] = media_rezagada(y_aj, pos, 14, 20, 3)
    df["media_28"] = media_rezagada(y_aj, pos, 14, 41, 7)
    df["media_91"] = media_rezagada(y_aj, pos, 14, 104, 20)
    df["media_mismo_dia"] = np.nanmean(df[["lag_14", "lag_21", "lag_28", "lag_35"]].to_numpy(), axis=1) \
        if len(df) else np.array([])
    df["tendencia_7_91"] = df.media_7 / (df.media_91 + 0.1)
    df["tasa_quiebre_28"] = media_rezagada(quiebre.astype(float), pos, 14, 41, 7)

    # el año pasado: cómo se movía la venta entre "hace 14 días" y "hoy" (rampa de la temporada)
    ly_hoy = media_rezagada(y_aj, pos, 357, 371, 5)
    ly_base = media_rezagada(y_aj, pos, 378, 405, 7)
    df["estacional_ly"] = ly_hoy / (ly_base + 0.1)
    df["media_28_x_estacional"] = df.media_28 * df.estacional_ly

    f = pd.DatetimeIndex(df.fecha)
    df["dia_semana"] = f.dayofweek
    df["dia_mes"] = f.day
    df["mes"] = f.month
    df["dia_anio"] = f.dayofyear
    df["feriado"] = es_feriado(f).astype(int)
    df["vispera_feriado"] = es_feriado(f + pd.Timedelta(days=1)).astype(int)
    df["quincena"] = es_quincena(f).astype(int)
    df["dias_abierto"] = np.minimum((df.fecha - df.apertura).dt.days, 400)

    # promociones: vigente, día de campaña y días desde que terminó la última
    en_promo = df.descuento.to_numpy() > 0
    ultimo_promo = pd.Series(np.where(en_promo, np.arange(len(df)), np.nan))
    ultimo_promo = ultimo_promo.groupby([df.id_local, df.id_producto], sort=False).ffill().to_numpy()
    dias_desde = np.arange(len(df)) - ultimo_promo
    df["dias_desde_promo"] = np.where(np.isnan(dias_desde) | (dias_desde > 30), 31, dias_desde)

    for c in CATEGORICAS:
        df[c] = df[c].astype("category")

    df["objetivo"] = np.where(quiebre & tratar_quiebres, np.nan, y)
    return df


COLUMNAS = [
    "lag_14", "lag_21", "lag_28", "lag_35", "lag_364", "media_7", "media_28", "media_91",
    "media_mismo_dia", "tendencia_7_91", "tasa_quiebre_28", "estacional_ly", "media_28_x_estacional",
    "dia_semana", "dia_mes", "mes", "dia_anio", "feriado", "vispera_feriado", "quincena",
    "dias_abierto", "descuento", "dia_de_promo", "dias_desde_promo", *CATEGORICAS,
]
