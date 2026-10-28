"""
Simulación de reposición: qué habría pasado en el periodo del backtest con otra
regla de pedido, usando la misma demanda.

Cada lunes se pide hasta un stock objetivo S (pedido = S - stock - en tránsito)
y el pedido llega después del lead time del local. Políticas:

- regla_actual: S = promedio de venta de 28 días x días de cobertura (12 Lima, 15 provincia).
  Es la regla con la que se generó la historia, así que su simulación tiene que
  reproducir la historia real: es la prueba de que el simulador está bien.
- pronostico: S = suma del pronóstico para los días que cubre el pedido.
- pronostico_p90 / pronostico_p95: lo mismo más un margen calibrado con conformal
  para cubrir la demanda de la ventana 9 (o 19) de cada 10 (o 20) veces.

Para simular hace falta la demanda que hubo, no la venta (con otra política se
habría vendido distinto). Aquí sale de la tabla `demanda_latente` del generador;
con datos reales habría que estimarla.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import CORTES_CALIBRACION, Backtest
from .datos import CLAVE, Base

POLITICAS = ["regla_actual", "pronostico", "pronostico_p90", "pronostico_p95"]
NIVEL = {"pronostico": None, "pronostico_p90": 0.9, "pronostico_p95": 0.95}
STOCK_MINIMO = 2


@dataclass
class Simulacion:
    politica: str
    diario: pd.DataFrame  # fecha x serie: demanda, venta, stock_cierre
    inicio: pd.Timestamp
    fin: pd.Timestamp


def _matriz(df: pd.DataFrame, valor: str, fechas: pd.DatetimeIndex, series: pd.MultiIndex) -> np.ndarray:
    t = df.pivot_table(index="fecha", columns=CLAVE, values=valor, aggfunc="first")
    return t.reindex(index=fechas, columns=series).to_numpy()


def periodo(bt: Backtest, base: Base) -> tuple[pd.Timestamp, pd.Timestamp, list[pd.Timestamp]]:
    """
    Va del primer corte con calibración de pedidos hasta 14 días después del último
    corte, que es lo que cubren los pronósticos.
    """
    inicio = bt.cortes[min(CORTES_CALIBRACION, len(bt.cortes) - 1)]
    fin = min(base.ultimo_dia, bt.cortes[-1] + pd.Timedelta(days=14))
    lunes = [d for d in pd.date_range(inicio, fin, freq="7D")]
    return inicio, fin, lunes


def objetivos_pronostico(bt: Backtest, decision: pd.Timestamp, series: pd.MultiIndex,
                         nivel: float | None) -> np.ndarray:
    """Suma del pronóstico para los días que cubre el pedido del lunes `decision`."""
    corte = max(c for c in bt.cortes if c <= decision)
    desfase = (decision - corte).days
    p = bt.predicciones
    m = (p.corte == corte) & (p.horizonte > desfase) & (p.horizonte <= desfase + p.cobertura)
    g = p[m].groupby(CLAVE, observed=True).agg(lgbm=("lgbm", "sum"), segmento=("segmento", "first"))
    g = g.reindex(series)
    s = g.lgbm.fillna(0).to_numpy()
    if nivel is not None:
        cal = bt.calibradores_suma.get(corte)
        if cal is not None:
            s = cal.aplicar(s, g.segmento.fillna("baja"), nivel)
    return s


def simular(base: Base, bt: Backtest, politica: str) -> Simulacion:
    if base.latente is None:
        raise ValueError("La simulación necesita la demanda latente: cargar(..., con_latente=True)")
    if politica not in POLITICAS:
        raise ValueError(f"Política desconocida: {politica}")
    inicio, fin, lunes = periodo(bt, base)
    fechas = pd.date_range(inicio, fin, freq="D")
    v = base.ventas
    series = pd.MultiIndex.from_frame(v.loc[v.fecha == inicio, CLAVE].drop_duplicates())
    locales = base.locales.set_index("id_local").loc[series.get_level_values("id_local")]
    lead = locales.lead_time_dias.to_numpy()
    cobertura = locales.cobertura_dias.to_numpy()

    demanda = _matriz(base.latente[base.latente.fecha.between(inicio, fin)], "demanda", fechas, series)
    previo = v[(v.fecha > inicio - pd.Timedelta(days=28)) & (v.fecha <= inicio)]
    historia = _matriz(previo, "unidades", pd.date_range(inicio - pd.Timedelta(days=27), inicio), series)
    stock = _matriz(v[v.fecha == inicio], "stock_cierre", fechas[:1], series)[0].astype(np.int64)

    n_d, n_s = len(fechas), len(series)
    llegadas = np.zeros((n_d + 20, n_s), dtype=np.int64)
    en_transito = np.zeros(n_s, dtype=np.int64)
    venta = np.zeros((n_d, n_s), dtype=np.int64)
    cierre = np.zeros((n_d, n_s), dtype=np.int64)
    cierre[0] = stock
    decisiones = set(lunes)

    def pedir(t: int, fecha: pd.Timestamp) -> None:
        nonlocal en_transito
        if politica == "regla_actual":
            s = historia.mean(axis=0) * cobertura
        else:
            s = objetivos_pronostico(bt, fecha, series, NIVEL[politica])
        s = np.maximum(np.ceil(s - 1e-9), STOCK_MINIMO)
        pedido = np.maximum(s - stock - en_transito, 0).astype(np.int64)
        llegadas[t + lead, np.arange(n_s)] += pedido
        en_transito = en_transito + pedido

    # la ventana de 28 días es circular, igual que en el generador
    hist_pos = {d: i for i, d in enumerate(pd.date_range(inicio - pd.Timedelta(days=27), inicio))}
    orden = np.array([(pd.Timestamp(d) - pd.Timestamp("2024-01-01")).days % 28 for d in hist_pos])
    historia = historia[np.argsort(orden)]

    pedir(0, inicio)
    for t in range(1, n_d):
        llega = llegadas[t]
        stock = stock + llega
        en_transito = en_transito - llega
        vende = np.minimum(demanda[t], stock).astype(np.int64)
        stock = stock - vende
        venta[t] = vende
        cierre[t] = stock
        historia[(fechas[t] - pd.Timestamp("2024-01-01")).days % 28] = vende
        if fechas[t] in decisiones:
            pedir(t, fechas[t])

    idx = pd.MultiIndex.from_product([fechas[1:], range(n_s)], names=["fecha", "serie"])
    diario = pd.DataFrame({
        "demanda": demanda[1:].ravel(), "venta": venta[1:].ravel(), "stock_cierre": cierre[1:].ravel(),
    }, index=idx).reset_index()
    diario["id_local"] = np.tile(series.get_level_values("id_local"), n_d - 1)
    diario["id_producto"] = np.tile(series.get_level_values("id_producto"), n_d - 1)
    return Simulacion(politica, diario.drop(columns="serie"), fechas[1], fin)


def indicadores(sim: Simulacion, base: Base, por: str | None = None) -> pd.DataFrame:
    """Nivel de servicio, quiebres, inventario y venta perdida."""
    d = sim.diario.merge(base.productos[["id_producto", "categoria", "costo"]], on="id_producto")
    precios = base.ventas[["fecha", *CLAVE, "precio_unitario"]]
    d = d.merge(precios, on=["fecha", *CLAVE], how="left")
    d["perdida"] = (d.demanda - d.venta) * d.precio_unitario
    d["inventario_costo"] = d.stock_cierre * d.costo
    d["demanda_costo"] = d.demanda * d.costo

    def _f(g):
        dias = g.fecha.nunique()
        return pd.Series({
            "nivel_servicio": g.venta.sum() / g.demanda.sum(),
            "dias_con_quiebre": float((g.stock_cierre == 0).mean()),
            "venta_perdida": g.perdida.sum(),
            "inventario_promedio": g.inventario_costo.sum() / dias,
            "dias_de_inventario": g.inventario_costo.sum() / g.demanda_costo.sum(),
        })
    if por is None:
        r = _f(d).to_frame().T
    else:
        r = d.groupby(por)[d.columns.tolist()].apply(_f).reset_index()
    r.insert(0, "politica", sim.politica)
    return r
