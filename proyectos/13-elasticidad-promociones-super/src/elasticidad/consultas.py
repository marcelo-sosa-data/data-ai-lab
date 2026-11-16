"""Consultas SQL sobre la base de Qollqa: panel por formato y matrices de precios."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

FORMATOS = ["Hiper", "Super", "Express"]


def conectar(ruta: str | Path) -> duckdb.DuckDBPyConnection:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No encuentro la base en {ruta}. Genérala con: python -m elasticidad generar")
    return duckdb.connect(str(ruta), read_only=True)


PANEL_SQL = """
SELECT v.semana, t.formato, v.id_sku, SUM(v.unidades) AS unidades, COUNT(*) AS locales
FROM ventas_semana v
JOIN tiendas t USING (id_tienda)
GROUP BY ALL
ORDER BY v.semana, t.formato, v.id_sku
"""


@dataclass
class Matrices:
    """Precios, costos y ventas en forma (semana, sku); ventas por (formato, semana, sku)."""

    semanas: pd.DatetimeIndex
    skus: pd.DataFrame          # id_sku, descripcion, marca, categoria, marca_propia (en orden)
    categorias: list[str]
    precio: np.ndarray
    regular: np.ndarray
    costo: np.ndarray
    encarte: np.ndarray
    aporte: np.ndarray
    unidades: np.ndarray        # (F, T, P)
    locales: np.ndarray         # (F,) cantidad de locales por formato

    @property
    def cat_de_sku(self) -> np.ndarray:
        return self.skus.categoria.map({c: i for i, c in enumerate(self.categorias)}).to_numpy()

    def recortar(self, n: int) -> "Matrices":
        """Las primeras n semanas (para ajustar con lo conocido hasta un corte)."""
        return Matrices(self.semanas[:n], self.skus, self.categorias, self.precio[:n], self.regular[:n],
                        self.costo[:n], self.encarte[:n], self.aporte[:n], self.unidades[:, :n], self.locales)


def matrices(con: duckdb.DuckDBPyConnection) -> Matrices:
    skus = con.execute("SELECT * FROM productos ORDER BY id_sku").df()
    precios = con.execute("SELECT * FROM precios_semana ORDER BY semana, id_sku").df()
    semanas = pd.DatetimeIndex(sorted(precios.semana.unique()))
    T, P = len(semanas), len(skus)

    def ancho(col):
        return precios.pivot(index="semana", columns="id_sku", values=col)[skus.id_sku].to_numpy(float)

    panel = con.execute(PANEL_SQL).df()
    locales = panel.groupby("formato").locales.first().reindex(FORMATOS).to_numpy(float)
    u = np.zeros((len(FORMATOS), T, P))
    for f, formato in enumerate(FORMATOS):
        sub = panel[panel.formato == formato].pivot(index="semana", columns="id_sku", values="unidades")
        u[f] = sub.reindex(index=semanas.date, columns=skus.id_sku).fillna(0).to_numpy()
    categorias = list(dict.fromkeys(skus.categoria))
    return Matrices(semanas, skus, categorias, ancho("precio_venta"), ancho("precio_regular"),
                    ancho("costo_unitario"), ancho("encarte"), ancho("aporte_unitario"), u, locales)


def promociones(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT pr.*, p.descripcion, p.categoria, p.marca_propia
        FROM promociones pr JOIN productos p USING (id_sku)
        ORDER BY inicio, id_sku
    """).df()


def verdad_promos(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Margen incremental real de cada promoción (solo existe porque los datos son simulados)."""
    return con.execute("SELECT * FROM aux_promo_verdad").df()
