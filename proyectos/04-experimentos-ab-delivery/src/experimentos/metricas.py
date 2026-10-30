"""
Tablas por usuario expuesto, armadas en SQL sobre DuckDB.

La unidad de análisis es el usuario (es lo que se aleatoriza). Cada usuario cuenta
sus pedidos desde el día de su primera exposición hasta el fin de la ventana; la
covariable de CUPED es la misma métrica en los 28 días previos al inicio, que nadie
pudo afectar con el experimento.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .catalogo import DIAS_PRE

SQL_USUARIOS = """
WITH exp AS (
    SELECT ?::DATE AS inicio, ?::DATE AS fin
),
expuestos AS (
    SELECT x.id_usuario, x.variante, x.fecha_exposicion, u.ciudad, u.plataforma, u.version_app,
           u.fecha_registro < (SELECT inicio FROM exp) - INTERVAL {pre} DAY AS recurrente
    FROM exposiciones x
    JOIN usuarios u USING (id_usuario)
    WHERE x.id_experimento = ?
),
post AS (
    SELECT e.id_usuario,
           COUNT(*)                                     AS pedidos_creados,
           COUNT(*) FILTER (WHERE p.cancelado)          AS cancelados,
           COUNT(*) FILTER (WHERE NOT p.cancelado)      AS pedidos,
           SUM(p.monto) FILTER (WHERE NOT p.cancelado)  AS gmv,
           SUM(p.margen)                                AS margen
    FROM expuestos e
    JOIN pedidos p
      ON p.id_usuario = e.id_usuario
     AND p.fecha >= e.fecha_exposicion
     AND p.fecha <= (SELECT fin FROM exp)
    GROUP BY e.id_usuario
),
pre AS (
    SELECT e.id_usuario,
           COUNT(*) FILTER (WHERE NOT p.cancelado)      AS pedidos_pre,
           SUM(p.monto) FILTER (WHERE NOT p.cancelado)  AS gmv_pre,
           SUM(p.margen)                                AS margen_pre
    FROM expuestos e
    JOIN pedidos p
      ON p.id_usuario = e.id_usuario
     AND p.fecha >= (SELECT inicio FROM exp) - INTERVAL {pre} DAY
     AND p.fecha <  (SELECT inicio FROM exp)
    GROUP BY e.id_usuario
)
SELECT e.*,
       COALESCE(post.pedidos_creados, 0)  AS pedidos_creados,
       COALESCE(post.cancelados, 0)       AS cancelados,
       COALESCE(post.pedidos, 0)          AS pedidos,
       COALESCE(post.gmv, 0)              AS gmv,
       COALESCE(post.margen, 0)           AS margen,
       (COALESCE(post.pedidos, 0) > 0)::INT AS conversion,
       COALESCE(pre.pedidos_pre, 0)       AS pedidos_pre,
       COALESCE(pre.gmv_pre, 0)           AS gmv_pre,
       COALESCE(pre.margen_pre, 0)        AS margen_pre,
       (COALESCE(pre.pedidos_pre, 0) > 0)::INT AS conversion_pre
FROM expuestos e
LEFT JOIN post USING (id_usuario)
LEFT JOIN pre USING (id_usuario)
ORDER BY e.id_usuario
""".format(pre=DIAS_PRE)

SQL_DIARIO = """
-- pedidos entregados por usuario y día de la ventana (para la lectura secuencial)
SELECT x.id_usuario, p.fecha, COUNT(*) AS pedidos, SUM(p.monto) AS gmv
FROM exposiciones x
JOIN pedidos p
  ON p.id_usuario = x.id_usuario
 AND p.fecha >= x.fecha_exposicion
 AND p.fecha <= ?::DATE
WHERE x.id_experimento = ? AND NOT p.cancelado
GROUP BY ALL
"""


def conectar(ruta: Path) -> duckdb.DuckDBPyConnection:
    if not Path(ruta).exists():
        raise FileNotFoundError(f"No existe {ruta}. Corre primero: python -m experimentos generar")
    return duckdb.connect(str(ruta), read_only=True)


def tabla_usuarios(con, id_exp: str, inicio, fin) -> pd.DataFrame:
    df = con.execute(SQL_USUARIOS, [str(inicio)[:10], str(fin)[:10], id_exp]).df()
    df["fecha_exposicion"] = pd.to_datetime(df.fecha_exposicion)
    df["tratamiento"] = df.variante.eq("tratamiento")
    df["region"] = np.where(df.ciudad.eq("Lima"), "Lima", "provincia")
    return df


def acumulado_diario(con, id_exp: str, usuarios: pd.DataFrame, inicio, fin, metrica: str = "pedidos"):
    """
    Matriz usuarios x días con la métrica acumulada a cada día de la ventana, y la
    máscara de quién ya estaba expuesto. Es lo que vería alguien mirando el tablero cada mañana.
    """
    dias = pd.date_range(inicio, fin, freq="D")
    d = con.execute(SQL_DIARIO, [str(fin)[:10], id_exp]).df()
    pos_u = pd.Series(np.arange(len(usuarios)), index=usuarios.id_usuario.to_numpy())
    m = np.zeros((len(usuarios), len(dias)))
    if len(d):
        iu = pos_u.reindex(d.id_usuario.to_numpy()).to_numpy()
        ok = ~np.isnan(iu)
        idia = (pd.to_datetime(d.fecha) - dias[0]).dt.days.to_numpy()
        np.add.at(m, (iu[ok].astype(int), idia[ok]), d[metrica].to_numpy()[ok])
    expo = (usuarios.fecha_exposicion.to_numpy()[:, None] <= dias.to_numpy()[None, :])
    return dias, np.cumsum(m, axis=1), expo
