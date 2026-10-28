"""
Backtest con origen móvil: en cada corte se entrena con lo conocido hasta ese día
y se pronostican los siguientes días. Los cortes caen en lunes, que es cuando la
cadena hace el pedido.

Cada corte predice 21 días: los 14 primeros se usan para medir el error; los
siguientes los necesita la simulación de reposición, que decide cada lunes pero
reentrena cada dos semanas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import features as ft
from .datos import CLAVE, Base, armar_panel, segmento_rotacion
from .intervalos import Calibrador
from .metricas import cobertura, resumen
from .modelos import ModeloGlobal, naive_estacional, promedio_28

HORIZONTE = 14
DIAS_PREDICCION = 21
MODELOS = ["promedio_28", "naive_estacional", "lgbm_sin_tratar", "lgbm"]
CORTES_CALIBRACION = 2


def cortes_por_defecto(base: Base, n: int = 13, cada: int = 14) -> list[pd.Timestamp]:
    """Últimos `n` lunes, cada `cada` días, dejando 14 días de datos después del último."""
    ultimo = base.ultimo_dia - pd.Timedelta(days=HORIZONTE)
    ultimo -= pd.Timedelta(days=ultimo.dayofweek)
    return [ultimo - pd.Timedelta(days=cada * i) for i in range(n)][::-1]


def cobertura_dias(region: pd.Series, lead_time: dict[str, int]) -> np.ndarray:
    """
    Días que tiene que cubrir el pedido del lunes T. Llega la mañana de T+L y el
    siguiente llega la mañana de T+7+L, así que cubre la demanda de T+1 a T+6+L.
    """
    return 6 + region.astype(str).map(lead_time).to_numpy()


@dataclass
class Backtest:
    predicciones: pd.DataFrame
    cortes: list[pd.Timestamp]
    calibradores: dict[pd.Timestamp, Calibrador] = field(default_factory=dict)
    calibradores_suma: dict[pd.Timestamp, Calibrador] = field(default_factory=dict)
    importancia: pd.DataFrame | None = None


def correr(base: Base, cortes: list[pd.Timestamp] | None = None, rondas: int | None = None,
           progreso: Callable[[int, int, pd.Timestamp], None] | None = None) -> Backtest:
    cortes = cortes or cortes_por_defecto(base)
    panel = armar_panel(base)
    feats = {True: ft.construir(panel, True), False: ft.construir(panel, False)}
    lead = dict(base.locales[["region", "lead_time_dias"]].drop_duplicates().itertuples(index=False))

    bloques, importancia = [], None
    for i, corte in enumerate(cortes):
        if progreso:
            progreso(i, len(cortes), corte)
        f = feats[True]
        sel = ((f.fecha > corte) & (f.fecha <= corte + pd.Timedelta(days=DIAS_PREDICCION))).to_numpy()
        filas = f.loc[sel, ["fecha", *CLAVE, "categoria", "region", "unidades", "quiebre",
                            "media_91"]].copy()
        filas["corte"] = corte
        filas["horizonte"] = (filas.fecha - corte).dt.days
        filas["segmento"] = segmento_rotacion(filas.media_91.fillna(0))
        filas["promedio_28"] = promedio_28(panel, corte, filas)
        filas["naive_estacional"] = naive_estacional(panel, corte, filas)
        kw = {} if rondas is None else {"rondas": rondas}
        m0 = ModeloGlobal(**kw).entrenar(feats[False], corte)
        filas["lgbm_sin_tratar"] = m0.predecir(feats[False].loc[sel])
        m1 = ModeloGlobal(**kw).entrenar(f, corte)
        filas["lgbm"] = m1.predecir(f.loc[sel])
        if i == len(cortes) - 1:
            importancia = m1.importancia()
        bloques.append(filas.drop(columns="media_91"))

    pred = pd.concat(bloques, ignore_index=True)
    pred["cobertura"] = cobertura_dias(pred.region, lead)
    bt = Backtest(pred, list(cortes), importancia=importancia)
    _calibrar(bt)
    return bt


def _calibrar(bt: Backtest) -> None:
    """Para cada corte, calibra con los errores de los cortes anteriores (nunca con los propios)."""
    p = bt.predicciones
    p["lgbm_p10"] = np.nan
    p["lgbm_p90"] = np.nan
    sumas = sumas_por_ventana(p)
    for i, corte in enumerate(bt.cortes):
        previos = bt.cortes[max(0, i - CORTES_CALIBRACION):i]
        if not previos:
            continue
        cal = p[p.corte.isin(previos) & (p.horizonte <= HORIZONTE) & ~p.quiebre]
        c = Calibrador.ajustar(cal.unidades, cal.lgbm, cal.segmento)
        bt.calibradores[corte] = c
        m = (p.corte == corte).to_numpy()
        p.loc[m, "lgbm_p10"] = c.aplicar(p.loc[m, "lgbm"], p.loc[m, "segmento"], 0.1)
        p.loc[m, "lgbm_p90"] = c.aplicar(p.loc[m, "lgbm"], p.loc[m, "segmento"], 0.9)

        s = sumas[sumas.corte.isin(previos) & ~sumas.hubo_quiebre]
        bt.calibradores_suma[corte] = Calibrador.ajustar(s.unidades, s.lgbm, s.segmento, niveles=(0.9, 0.95))


def sumas_por_ventana(p: pd.DataFrame) -> pd.DataFrame:
    """
    Venta y pronóstico acumulados en la ventana que cubre un pedido, para cada serie
    y corte. Hay dos ventanas por corte (pedido del lunes del corte y del siguiente).
    """
    salida = []
    for desfase in (0, 7):
        h = p.horizonte - desfase
        m = (h >= 1) & (h <= p.cobertura)
        g = p[m].groupby(["corte", *CLAVE], observed=True)
        s = g.agg(unidades=("unidades", "sum"), lgbm=("lgbm", "sum"), promedio_28=("promedio_28", "sum"),
                  hubo_quiebre=("quiebre", "any"), segmento=("segmento", "first"),
                  dias=("horizonte", "size"), cobertura=("cobertura", "first")).reset_index()
        s = s[s.dias == s.cobertura]  # al final de los datos la ventana queda incompleta
        s["desfase"] = desfase
        salida.append(s)
    return pd.concat(salida, ignore_index=True)


# --------------------------------------------------------------------------
# Resúmenes
# --------------------------------------------------------------------------

def tabla_modelos(p: pd.DataFrame, latente: pd.DataFrame | None = None) -> pd.DataFrame:
    """Error diario de cada modelo en los primeros 14 días, en días sin quiebre."""
    ev = p[(p.horizonte <= HORIZONTE) & ~p.quiebre]
    filas = []
    for m in MODELOS:
        r = resumen(ev, "unidades", m).iloc[0]
        fila = {"modelo": m, "wape": r.wape, "sesgo": r.sesgo}
        s = sumas_modelo(p, m)
        fila["wape_semana"] = resumen(s, "unidades", "pred").iloc[0].wape
        if latente is not None:
            todo = p[p.horizonte <= HORIZONTE].merge(latente, on=["fecha", *CLAVE])
            fila["sesgo_vs_demanda"] = resumen(todo, "demanda", m).iloc[0].sesgo
            q = todo[todo.quiebre]
            fila["sesgo_en_quiebres"] = resumen(q, "demanda", m).iloc[0].sesgo if len(q) else np.nan
        filas.append(fila)
    return pd.DataFrame(filas)


def sumas_modelo(p: pd.DataFrame, modelo: str) -> pd.DataFrame:
    """Venta semanal (horizonte 1-7 y 8-14) por serie, sin semanas con quiebre."""
    ev = p[p.horizonte <= HORIZONTE].assign(semana=lambda d: (d.horizonte - 1) // 7)
    g = ev.groupby(["corte", "semana", *CLAVE], observed=True).agg(
        unidades=("unidades", "sum"), pred=(modelo, "sum"), q=("quiebre", "any")).reset_index()
    return g[~g.q]


def tabla_segmentos(p: pd.DataFrame, por: str = "segmento") -> pd.DataFrame:
    ev = p[(p.horizonte <= HORIZONTE) & ~p.quiebre]
    a = resumen(ev, "unidades", "promedio_28", [por]).rename(columns={"wape": "wape_promedio_28",
                                                                     "sesgo": "sesgo_promedio_28"})
    b = resumen(ev, "unidades", "lgbm", [por])[[por, "wape", "sesgo"]].rename(
        columns={"wape": "wape_lgbm", "sesgo": "sesgo_lgbm"})
    t = a.merge(b, on=por)
    t["mejora"] = 1 - t.wape_lgbm / t.wape_promedio_28
    return t[[por, "unidades", "wape_promedio_28", "wape_lgbm", "mejora", "sesgo_promedio_28", "sesgo_lgbm"]]


def tabla_cobertura(p: pd.DataFrame) -> pd.DataFrame:
    ev = p[(p.horizonte <= HORIZONTE) & ~p.quiebre & p.lgbm_p10.notna()]
    filas = [{"segmento": "total", "cobertura": cobertura(ev.unidades, ev.lgbm_p10, ev.lgbm_p90),
              "ancho_medio": float((ev.lgbm_p90 - ev.lgbm_p10).mean()), "filas": len(ev)}]
    for s, g in ev.groupby("segmento"):
        filas.append({"segmento": s, "cobertura": cobertura(g.unidades, g.lgbm_p10, g.lgbm_p90),
                      "ancho_medio": float((g.lgbm_p90 - g.lgbm_p10).mean()), "filas": len(g)})
    return pd.DataFrame(filas)


def calibradores_vigentes(bt: Backtest) -> tuple[Calibrador, Calibrador]:
    """Calibración para el pronóstico de hoy: los errores de los últimos cortes."""
    p = bt.predicciones
    ultimos = bt.cortes[-CORTES_CALIBRACION:]
    cal = p[p.corte.isin(ultimos) & (p.horizonte <= HORIZONTE) & ~p.quiebre]
    s = sumas_por_ventana(p)
    s = s[s.corte.isin(ultimos) & ~s.hubo_quiebre]
    return (Calibrador.ajustar(cal.unidades, cal.lgbm, cal.segmento),
            Calibrador.ajustar(s.unidades, s.lgbm, s.segmento, niveles=(0.9, 0.95)))
