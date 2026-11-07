"""
Resumen RFM en SQL, en el formato que esperan los modelos de pymc-marketing.

Para el modelo, una "compra" es un día con ingreso neto positivo: un día
con solo transferencias (que no dejan ingreso) no cuenta. Las unidades son días.

  frequency       días con ingreso después del primero
  recency         días entre el primero y el último
  T               días entre el primero y el corte
  monetary_value  ingreso promedio de los días repetidos (sin el primero)
"""

from __future__ import annotations

from datetime import date

import pandas as pd

SQL_DIAS = """
SELECT id_cliente, fecha_hora::DATE AS dia, SUM(ingreso_neto) AS ingreso
FROM transacciones
WHERE fecha_hora < ?::DATE + 1
GROUP BY ALL
HAVING SUM(ingreso_neto) > 0
"""


def rfm(con, corte: date, desde: date | None = None) -> pd.DataFrame:
    """
    RFM de cada cliente cuya primera compra cae entre `desde` y `corte`
    (con T >= 1, para que el modelo tenga algo que mirar).
    """
    desde = desde or date(1900, 1, 1)
    df = con.execute(f"""
        WITH d AS ({SQL_DIAS}),
        r AS (
            SELECT id_cliente,
                   COUNT(*) - 1 AS frequency,
                   datediff('day', MIN(dia), MAX(dia)) AS recency,
                   datediff('day', MIN(dia), ?::DATE) AS T,
                   COALESCE((SUM(ingreso) - arg_min(ingreso, dia)) / NULLIF(COUNT(*) - 1, 0), 0)
                       AS monetary_value,
                   MIN(dia) AS primera_compra,
                   arg_min(ingreso, dia) AS ingreso_primera,
                   SUM(ingreso) AS ingreso_historico
            FROM d GROUP BY id_cliente
        )
        SELECT r.id_cliente AS customer_id, c.canal, c.region,
               date_trunc('month', c.fecha_activacion)::DATE AS cohorte, r.*  EXCLUDE (id_cliente)
        FROM r JOIN clientes c USING (id_cliente)
        WHERE r.primera_compra >= ? AND r.T >= 1
        ORDER BY customer_id
    """, [corte, corte, desde]).df()
    for c in ("frequency", "recency", "T"):
        df[c] = df[c].astype(float)
    return df


def compras_en_ventana(con, desde: date, hasta: date) -> pd.DataFrame:
    """Días con ingreso e ingreso neto de cada cliente entre dos fechas (inclusive)."""
    return con.execute("""
        WITH d AS (
            SELECT id_cliente, fecha_hora::DATE AS dia, SUM(ingreso_neto) AS ingreso
            FROM transacciones
            WHERE fecha_hora >= ?::DATE AND fecha_hora < ?::DATE + 1
            GROUP BY ALL HAVING SUM(ingreso_neto) > 0
        )
        SELECT id_cliente AS customer_id, COUNT(*) AS compras_real, SUM(ingreso) AS ingreso_real
        FROM d GROUP BY ALL
    """, [desde, hasta]).df()


def compras_semanales(con, desde: date, hasta: date, clientes: pd.Series) -> pd.DataFrame:
    """Días con ingreso por semana desde `desde`, solo de los clientes indicados."""
    con.register("ids", pd.DataFrame({"customer_id": clientes.to_numpy()}))
    try:
        return con.execute("""
            WITH d AS (
                SELECT id_cliente, fecha_hora::DATE AS dia
                FROM transacciones
                WHERE fecha_hora >= ?::DATE AND fecha_hora < ?::DATE + 1
                  AND id_cliente IN (SELECT customer_id FROM ids)
                GROUP BY ALL HAVING SUM(ingreso_neto) > 0
            )
            SELECT datediff('day', ?::DATE, dia) // 7 AS semana, COUNT(*) AS compras_real
            FROM d GROUP BY ALL ORDER BY semana
        """, [desde, hasta, desde]).df()
    finally:
        con.unregister("ids")
