"""El tablero actual y la referencia con datos completos, en SQL sobre el log.

El tablero de Operaciones se refresca cada 15 minutos: toma del log de
eventos lo que llegó hasta ese momento, suma las filas del último bloque
(sin quitar reintentos) y pinta en rojo la zona si más de 35% de las
asignaciones del bloque esperó más de 6 minutos. Lo que llega tarde ya
no entra a su bloque, porque cada refresco solo agrega el bloque nuevo.

Para separar el efecto de la cadencia del efecto de la métrica también
se calcula la cola de pedidos sin motorizado con cualquier cadencia,
mirando lo que había llegado (lo que vería un batch) o lo que de verdad
había pasado (la referencia: lo mejor que se puede hacer con la regla).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd

from .agregados import evaluar_serie
from .config import Regla


def conectar(ruta_eventos: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW eventos AS SELECT * FROM read_parquet('{Path(ruta_eventos).as_posix()}')")
    con.execute("""
        CREATE TABLE pedidos AS
        SELECT pedido_id,
               any_value(zona) AS zona,
               min(ts_evento) FILTER (tipo = 'creado') AS ev_creado,
               min(ts_recibido) FILTER (tipo = 'creado') AS lleg_creado,
               min(ts_evento) FILTER (tipo IN ('asignado', 'cancelado')) AS ev_cierre,
               min(ts_recibido) FILTER (tipo IN ('asignado', 'cancelado')) AS lleg_cierre
        FROM eventos GROUP BY pedido_id
    """)
    return con


def _cortes(con, cada_min: int) -> None:
    """Tabla `cortes` con los momentos de refresco de cada día de operación."""
    con.execute(f"""
        CREATE OR REPLACE TABLE cortes AS
        WITH dias AS (SELECT DISTINCT date_trunc('day', ts_evento) AS d FROM eventos
                      WHERE tipo = 'creado')
        SELECT d + INTERVAL 10 HOUR + INTERVAL (k * {cada_min}) MINUTE AS corte
        FROM dias, range(1, (14 * 60) // {cada_min} + 1) t(k)
    """)


def tablero_demoradas(con, regla: Regla, cada_min: int = 15) -> pd.DataFrame:
    """Métrica del tablero actual por zona y bloque, con lo que había llegado al refrescar."""
    _cortes(con, cada_min)
    return con.execute(f"""
        WITH zonas AS (SELECT DISTINCT zona FROM eventos),
        base AS (SELECT c.corte, z.zona FROM cortes c, zonas z),
        bloque AS (
            SELECT c.corte, e.zona,
                   count(*) FILTER (e.tipo = 'creado') AS creados,
                   count(*) FILTER (e.tipo = 'asignado') AS asignados,
                   count(*) FILTER (e.tipo = 'asignado' AND e.espera_asignacion_s > {regla.demora_s}) AS demoradas,
                   count(*) FILTER (e.tipo = 'cancelado') AS cancelados
            FROM cortes c JOIN eventos e
              ON e.ts_evento >= c.corte - INTERVAL {cada_min} MINUTE AND e.ts_evento < c.corte
             AND e.ts_recibido <= c.corte
            GROUP BY ALL
        )
        SELECT b.corte, b.zona,
               coalesce(creados, 0) AS creados, coalesce(asignados, 0) AS asignados,
               coalesce(demoradas, 0) AS demoradas, coalesce(cancelados, 0) AS cancelados,
               coalesce(demoradas / nullif(asignados, 0), 0) AS ratio_demoradas,
               coalesce(asignados, 0) >= {regla.minimo_asignaciones}
                 AND coalesce(demoradas / nullif(asignados, 0), 0) >= {regla.umbral_demoradas} AS en_rojo
        FROM base b LEFT JOIN bloque USING (corte, zona)
        ORDER BY zona, corte
    """).df()


def cola_por_corte(con, regla: Regla, cada_min: int, con_llegada: bool) -> pd.DataFrame:
    """Pedidos sin motorizado hace más de la espera de la regla, en cada corte.

    Con `con_llegada` solo cuenta lo que había llegado al log en ese
    momento; sin él usa la hora real de cada evento.
    """
    _cortes(con, cada_min)
    creado, cierre = ("lleg_creado", "lleg_cierre") if con_llegada else ("ev_creado", "ev_cierre")
    return con.execute(f"""
        WITH zonas AS (SELECT DISTINCT zona FROM eventos),
        base AS (SELECT c.corte, z.zona FROM cortes c, zonas z),
        cola AS (
            SELECT c.corte, p.zona, count(*) AS sin_motorizado
            FROM cortes c JOIN pedidos p
              ON p.ev_creado <= c.corte - INTERVAL {int(regla.espera_sin_motorizado_s)} SECOND
             AND p.ev_creado >= c.corte - INTERVAL {int(regla.pendiente_vencido_s)} SECOND
             AND p.{creado} <= c.corte
             AND (p.{cierre} IS NULL OR p.{cierre} > c.corte)
            GROUP BY ALL
        )
        SELECT corte, zona, coalesce(sin_motorizado, 0) AS sin_motorizado
        FROM base LEFT JOIN cola USING (corte, zona)
        ORDER BY zona, corte
    """).df()


def alertas_de_serie(df: pd.DataFrame, columna_falla: str | None, regla: Regla,
                     por_evaluacion: bool) -> pd.DataFrame:
    """Convierte una serie por zona y corte en aperturas y cierres de alerta.

    Con `por_evaluacion` (los batch) basta un corte en rojo para abrir y
    uno en verde para cerrar: es lo que hace el supervisor con el tablero.
    """
    r = replace(regla, minutos_para_abrir=1, minutos_para_cerrar=1) if por_evaluacion else regla
    filas = []
    for zona, g in df.groupby("zona", sort=False):
        serie = []
        for f in g.itertuples(index=False):
            corte_ms = int(pd.Timestamp(f.corte).value // 1_000_000)
            cola = f.sin_motorizado if columna_falla is None else (
                r.umbral_sin_motorizado if getattr(f, columna_falla) else 0)
            serie.append({"zona": zona, "inicio_ms": corte_ms, "sin_motorizado": int(cola),
                          "emitido_ms": corte_ms})
        filas.extend(evaluar_serie(serie, r))
    return pd.DataFrame(filas, columns=["zona", "minuto_ms", "detectado_ms", "sin_motorizado",
                                        "accion", "abierta_ms", "pico"])


def cifras_tablero(con, cada_min: int = 15) -> dict:
    """Cuánto se aleja lo que mostró el tablero de lo que de verdad pasó."""
    _cortes(con, cada_min)
    r = con.execute(f"""
        WITH mostrado AS (
            SELECT e.tipo, count(*) AS n, count(*) FILTER (e.es_reintento) AS reintentos
            FROM cortes c JOIN eventos e
              ON e.ts_evento >= c.corte - INTERVAL {cada_min} MINUTE AND e.ts_evento < c.corte
             AND e.ts_recibido <= c.corte
            GROUP BY ALL
        ), verdad AS (
            SELECT tipo, count(*) AS n FROM eventos WHERE NOT es_reintento GROUP BY ALL
        )
        SELECT v.tipo, v.n AS verdad, m.n AS mostrado, m.reintentos,
               v.n - (m.n - m.reintentos) AS no_llegaron
        FROM verdad v JOIN mostrado m USING (tipo)
    """).df()
    return {fila.tipo: {"verdad": int(fila.verdad), "mostrado": int(fila.mostrado),
                        "reintentos": int(fila.reintentos), "no_llegaron": int(fila.no_llegaron)}
            for fila in r.itertuples()}
