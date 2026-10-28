"""
Pronóstico vigente y pedido sugerido: entrena con toda la historia, pronostica
los próximos 14 días y arma la lista de pedido para cada local.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from . import features as ft
from .backtest import HORIZONTE, cobertura_dias
from .datos import CLAVE, Base, armar_panel, segmento_rotacion
from .intervalos import Calibrador
from .modelos import ModeloGlobal


def pronosticar(base: Base, cal_diario: Calibrador, rondas: int | None = None) -> pd.DataFrame:
    panel = armar_panel(base, dias_futuro=HORIZONTE)
    feats = ft.construir(panel, tratar_quiebres=True)
    corte = base.ultimo_dia
    modelo = ModeloGlobal(**({} if rondas is None else {"rondas": rondas})).entrenar(feats, corte)
    futuro = feats[feats.es_futuro]
    out = futuro[["fecha", *CLAVE, "categoria", "region", "descuento"]].copy()
    out["segmento"] = segmento_rotacion(futuro.media_91.fillna(0))
    out["pronostico"] = modelo.predecir(futuro)
    out["p10"] = cal_diario.aplicar(out.pronostico, out.segmento, 0.1)
    out["p90"] = cal_diario.aplicar(out.pronostico, out.segmento, 0.9)
    out["horizonte"] = (out.fecha - corte).dt.days
    return out.reset_index(drop=True)


def en_transito(ruta_db, corte: pd.Timestamp) -> pd.DataFrame:
    con = duckdb.connect(str(ruta_db), read_only=True)
    try:
        return con.execute("""
            SELECT id_local, id_producto, SUM(unidades) AS en_transito
            FROM pedidos WHERE fecha_pedido <= ? AND fecha_llegada > ?
            GROUP BY ALL
        """, [corte, corte]).df()
    finally:
        con.close()


def pedido_sugerido(base: Base, futuro: pd.DataFrame, cal_suma: Calibrador,
                    transito: pd.DataFrame, nivel: float = 0.95) -> pd.DataFrame:
    """Pedido si se hiciera hoy: P95 de la demanda de la ventana menos stock y en tránsito."""
    lead = dict(base.locales[["region", "lead_time_dias"]].drop_duplicates().itertuples(index=False))
    f = futuro.copy()
    f["cobertura"] = cobertura_dias(f.region, lead)
    v = f[f.horizonte <= f.cobertura]
    g = v.groupby(CLAVE, observed=True).agg(demanda_esperada=("pronostico", "sum"),
                                            segmento=("segmento", "first"),
                                            dias=("horizonte", "size")).reset_index()
    g["stock_objetivo"] = np.maximum(np.ceil(cal_suma.aplicar(g.demanda_esperada, g.segmento, nivel)), 2)
    stock = base.ventas.loc[base.ventas.fecha == base.ultimo_dia, [*CLAVE, "stock_cierre"]]
    g = g.merge(stock, on=CLAVE, how="left").merge(transito, on=CLAVE, how="left")
    g["en_transito"] = g.en_transito.fillna(0).astype(int)
    g["stock_cierre"] = g.stock_cierre.fillna(0).astype(int)
    g["pedido"] = np.maximum(g.stock_objetivo - g.stock_cierre - g.en_transito, 0).astype(int)
    prod = base.productos[["id_producto", "nombre", "categoria", "costo"]]
    g = g.merge(prod, on="id_producto")
    g["costo_pedido"] = g.pedido * g.costo
    g["dias_de_stock"] = (g.stock_cierre + g.en_transito) / (g.demanda_esperada / g.dias).clip(lower=1e-6)
    return g.sort_values(["id_local", "categoria", "nombre"]).reset_index(drop=True)
