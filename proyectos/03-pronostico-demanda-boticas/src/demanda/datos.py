"""
Carga la base de la cadena y arma el panel diario por local y producto.

El panel tiene una fila por (local, producto, día) desde la apertura del local
hasta el último día con datos, más los días futuros que se quieran pronosticar
(con venta vacía y la promoción planificada, que sí se conoce de antemano).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

CLAVE = ["id_local", "id_producto"]


@dataclass
class Base:
    ventas: pd.DataFrame
    locales: pd.DataFrame
    productos: pd.DataFrame
    promociones: pd.DataFrame
    latente: pd.DataFrame | None = None

    @property
    def ultimo_dia(self) -> pd.Timestamp:
        return self.ventas.fecha.max()


def cargar(ruta: Path, con_latente: bool = False) -> Base:
    """Lee las tablas. La demanda latente solo se carga para evaluar o simular, nunca para entrenar."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}. Corre primero: python -m demanda generar")
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        ventas = con.execute("""
            SELECT fecha, id_local, id_producto, unidades, precio_unitario, stock_cierre,
                   unidades_recibidas
            FROM ventas_diarias ORDER BY id_local, id_producto, fecha
        """).df()
        locales = con.execute("SELECT * FROM locales ORDER BY id_local").df()
        productos = con.execute("SELECT * FROM productos ORDER BY id_producto").df()
        promos = con.execute("SELECT * FROM promociones ORDER BY inicio").df()
        latente = None
        if con_latente:
            latente = con.execute("""
                SELECT fecha, id_local, id_producto, unidades AS demanda
                FROM demanda_latente ORDER BY id_local, id_producto, fecha
            """).df()
    finally:
        con.close()
    for df in (ventas, latente):
        if df is not None:
            df["fecha"] = pd.to_datetime(df.fecha)
    locales["apertura"] = pd.to_datetime(locales.apertura)
    promos["inicio"] = pd.to_datetime(promos.inicio)
    promos["fin"] = pd.to_datetime(promos.fin)
    return Base(ventas, locales, productos, promos, latente)


def descuento_diario(promos: pd.DataFrame, fechas: pd.DatetimeIndex) -> pd.DataFrame:
    """Descuento vigente por (fecha, producto); 0 si no hay campaña."""
    filas = []
    for p in promos.itertuples():
        dias = pd.date_range(p.inicio, p.fin, freq="D")
        filas.append(pd.DataFrame({"fecha": dias, "id_producto": p.id_producto,
                                   "descuento": p.descuento,
                                   "dia_de_promo": np.arange(1, len(dias) + 1)}))
    if not filas:
        return pd.DataFrame(columns=["fecha", "id_producto", "descuento", "dia_de_promo"])
    d = pd.concat(filas, ignore_index=True)
    return d[d.fecha.isin(fechas)]


def armar_panel(base: Base, dias_futuro: int = 0) -> pd.DataFrame:
    """Panel completo (sin huecos) ordenado por serie y fecha, con atributos y promoción."""
    fin = base.ultimo_dia + pd.Timedelta(days=dias_futuro)
    fechas = pd.date_range(base.ventas.fecha.min(), fin, freq="D")
    series = base.ventas[CLAVE].drop_duplicates()
    grid = series.merge(pd.DataFrame({"fecha": fechas}), how="cross")
    grid = grid.merge(base.locales[["id_local", "region", "formato", "apertura"]], on="id_local")
    grid = grid[grid.fecha >= grid.apertura]

    panel = grid.merge(base.ventas, on=["fecha", *CLAVE], how="left")
    panel = panel.merge(base.productos[["id_producto", "categoria"]], on="id_producto")
    promo = descuento_diario(base.promociones, fechas)
    panel = panel.merge(promo, on=["fecha", "id_producto"], how="left")
    panel["descuento"] = panel.descuento.fillna(0.0)
    panel["dia_de_promo"] = panel.dia_de_promo.fillna(0).astype(int)
    panel["quiebre"] = panel.stock_cierre.eq(0)
    panel["es_futuro"] = panel.fecha > base.ultimo_dia
    panel = panel.sort_values([*CLAVE, "fecha"]).reset_index(drop=True)
    return panel


def segmento_rotacion(venta_media_diaria: pd.Series) -> pd.Series:
    """Alta (5+ u/día), media (1 a 5) o baja (<1). Sirve para calibrar intervalos y reportar."""
    return pd.cut(venta_media_diaria, [-np.inf, 1, 5, np.inf], right=False,
                  labels=["baja", "media", "alta"]).astype(str)
