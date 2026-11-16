"""
El método actual del área comercial, tal como se hace en la planilla.

Para estimar una promoción se toma la venta promedio del producto en las cuatro
semanas previas y se le aplica el alza que tuvo su última promoción, ajustada en
proporción al descuento. Si el producto nunca estuvo en promoción, se usa el alza
promedio por punto de descuento de la categoría. No mira a las otras marcas ni lo
que pasa después de la promoción, y el alza de la promoción anterior trae pegada
la temporada en que se hizo.
"""

from __future__ import annotations

import duckdb
import pandas as pd

ALZA_POR_PUNTO_DEFECTO = 0.03  # regla de dedo: 3% más unidades por punto de descuento

ESTIMACION_SQL = """
WITH venta AS (
    SELECT semana, id_sku, SUM(unidades) AS u
    FROM ventas_semana GROUP BY ALL
),
previas AS (           -- cuatro semanas antes de cada promoción
    SELECT pr.id_promo, AVG(v.u) AS base_4s
    FROM promociones pr
    JOIN venta v ON v.id_sku = pr.id_sku
     AND v.semana >= pr.inicio - INTERVAL 28 DAY AND v.semana < pr.inicio
    GROUP BY 1
),
durante AS (
    SELECT pr.id_promo, AVG(v.u) AS u_promo
    FROM promociones pr
    JOIN venta v ON v.id_sku = pr.id_sku AND v.semana BETWEEN pr.inicio AND pr.fin
    GROUP BY 1
),
precios AS (
    SELECT pr.id_promo,
           AVG(ps.precio_regular) AS precio_regular, AVG(ps.precio_venta) AS precio_promo,
           AVG(ps.costo_unitario) AS costo, AVG(ps.aporte_unitario) AS aporte
    FROM promociones pr
    JOIN precios_semana ps ON ps.id_sku = pr.id_sku AND ps.semana BETWEEN pr.inicio AND pr.fin
    GROUP BY 1
),
observado AS (
    SELECT pr.id_promo, pr.id_sku, p.categoria, pr.inicio, pr.fin, pr.semanas, pr.descuento,
           b.base_4s, d.u_promo, d.u_promo / b.base_4s - 1 AS alza_observada
    FROM promociones pr
    JOIN productos p USING (id_sku)
    LEFT JOIN previas b USING (id_promo)   -- las promociones del primer mes no tienen cuatro semanas previas
    JOIN durante d USING (id_promo)
),
con_historia AS (
    SELECT *,
        -- última promoción del mismo producto
        LAG(alza_observada) OVER w_sku AS alza_anterior,
        LAG(descuento) OVER w_sku AS descuento_anterior,
        LAG(fin) OVER w_sku AS fin_anterior,
        -- promedio de la categoría con lo que ya terminó
        AVG(alza_observada / descuento) OVER (
            PARTITION BY categoria ORDER BY inicio
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS alza_por_punto_cat
    FROM observado
    WINDOW w_sku AS (PARTITION BY id_sku ORDER BY inicio)
)
SELECT h.*, pc.precio_regular, pc.precio_promo, pc.costo, pc.aporte,
    CASE
        WHEN h.alza_anterior IS NOT NULL THEN h.alza_anterior * h.descuento / h.descuento_anterior
        WHEN h.alza_por_punto_cat IS NOT NULL THEN h.alza_por_punto_cat * h.descuento
        ELSE {defecto} * h.descuento * 100
    END AS alza_estimada
FROM con_historia h
JOIN precios pc USING (id_promo)
ORDER BY h.inicio, h.id_sku
"""


def estimar(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Estimación AS IS de cada promoción del calendario, con lo que se sabía antes de lanzarla."""
    df = con.execute(ESTIMACION_SQL.format(defecto=ALZA_POR_PUNTO_DEFECTO)).df()
    u_promo = df.base_4s * (1 + df.alza_estimada)
    margen_con = u_promo * (df.precio_promo - df.costo + df.aporte)
    margen_sin = df.base_4s * (df.precio_regular - df.costo)
    df["unid_incrementales_asis"] = (u_promo - df.base_4s) * df.semanas
    df["venta_incremental_asis"] = (u_promo * df.precio_promo - df.base_4s * df.precio_regular) * df.semanas
    df["margen_incremental_asis"] = (margen_con - margen_sin) * df.semanas
    return df
