"""
Consultas de cohortes en SQL (DuckDB).

La cohorte de un cliente es el mes de su activación (primera transacción) y
el mes de vida k cuenta meses calendario desde ahí: k = 0 es el mes en que
activó, aunque haya activado el día 28.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

FIN_OBSERVACION = date(2026, 10, 31)


def conectar(ruta: str | Path) -> duckdb.DuckDBPyConnection:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No encuentro la base en {ruta}. Genérala con: python -m cohortes generar")
    return duckdb.connect(str(ruta), read_only=True)


def fin_observacion(con) -> date:
    """Último día con datos: fin del último mes completo."""
    ultimo = con.execute("SELECT MAX(fecha_hora)::DATE FROM transacciones").fetchone()[0]
    return (pd.Timestamp(ultimo) + pd.offsets.MonthEnd(0)).date()


VISTA_ACTIVIDAD = """
CREATE OR REPLACE TEMP VIEW actividad_mensual AS
WITH base AS (
    SELECT id_cliente, canal, region,
           date_trunc('month', fecha_activacion)::DATE AS cohorte
    FROM clientes
    WHERE fecha_activacion IS NOT NULL
)
SELECT b.id_cliente, b.canal, b.region, b.cohorte,
       date_trunc('month', t.fecha_hora)::DATE AS mes,
       datediff('month', b.cohorte, date_trunc('month', t.fecha_hora)) AS k,
       COUNT(*) AS transacciones,
       SUM(t.ingreso_neto) AS ingreso
FROM base b
JOIN transacciones t USING (id_cliente)
GROUP BY ALL
"""


def _preparar(con) -> None:
    con.execute(VISTA_ACTIVIDAD)


def tamanio_cohortes(con, ultima_cohorte: date | None = None) -> pd.DataFrame:
    """Activaciones y gasto por cohorte y canal, con el CAC (gasto de medios + bonos / activaciones)."""
    ultima = ultima_cohorte or date(2100, 1, 1)
    return con.execute("""
        WITH act AS (
            SELECT date_trunc('month', fecha_activacion)::DATE AS cohorte, canal, COUNT(*) AS clientes
            FROM clientes WHERE fecha_activacion IS NOT NULL GROUP BY ALL
        ), reg AS (
            SELECT date_trunc('month', fecha_registro)::DATE AS cohorte, canal, COUNT(*) AS registros
            FROM clientes GROUP BY ALL
        )
        SELECT a.cohorte, a.canal, r.registros, a.clientes,
               COALESCE(g.gasto_medios, 0) + COALESCE(g.gasto_bonos, 0) AS gasto,
               COALESCE(g.gasto_bonos, 0) AS gasto_bonos,
               (COALESCE(g.gasto_medios, 0) + COALESCE(g.gasto_bonos, 0)) / a.clientes AS cac
        FROM act a
        LEFT JOIN reg r USING (cohorte, canal)
        LEFT JOIN gasto_marketing g ON g.mes = a.cohorte AND g.canal = a.canal
        WHERE a.cohorte <= ?
        ORDER BY a.cohorte, a.canal
    """, [ultima]).df()


def matriz_cohortes(con, por_canal: bool = True) -> pd.DataFrame:
    """
    Una fila por cohorte (y canal) y mes de vida k, con la retención (clientes
    con al menos una transacción en el mes / tamaño de la cohorte) y el
    ingreso neto acumulado por cliente activado.

    Solo hay filas para meses ya cerrados: la cohorte de setiembre 2026 tiene k = 0 y 1.
    """
    _preparar(con)
    fin = fin_observacion(con)
    dim = "canal" if por_canal else "'Todos'"
    return con.execute(f"""
        WITH tam AS (
            SELECT date_trunc('month', fecha_activacion)::DATE AS cohorte, {dim} AS canal, COUNT(*) AS clientes
            FROM clientes WHERE fecha_activacion IS NOT NULL GROUP BY ALL
        ), meses AS (
            SELECT t.cohorte, t.canal, t.clientes, k.k
            FROM tam t, range(0, 36) k(k)
            WHERE t.cohorte + to_months(k.k::INT) <= ?
        ), act AS (
            SELECT cohorte, {dim} AS canal, k,
                   COUNT(DISTINCT id_cliente) AS activos, SUM(ingreso) AS ingreso
            FROM actividad_mensual GROUP BY ALL
        )
        SELECT m.cohorte, m.canal, m.k, m.clientes,
               COALESCE(a.activos, 0) AS activos,
               COALESCE(a.activos, 0) / m.clientes AS retencion,
               COALESCE(a.ingreso, 0) AS ingreso,
               SUM(COALESCE(a.ingreso, 0)) OVER w / m.clientes AS ingreso_acum_cliente
        FROM meses m LEFT JOIN act a USING (cohorte, canal, k)
        WINDOW w AS (PARTITION BY m.cohorte, m.canal ORDER BY m.k)
        ORDER BY m.canal, m.cohorte, m.k
    """, [fin]).df()


def retencion_promedio(matriz: pd.DataFrame, max_k: int = 18) -> pd.DataFrame:
    """Curva de retención por canal ponderada por tamaño de cohorte (solo cohortes que llegaron a cada k)."""
    m = matriz[matriz.k <= max_k]
    g = m.groupby(["canal", "k"]).agg(activos=("activos", "sum"), clientes=("clientes", "sum"),
                                      ingreso=("ingreso", "sum"), cohortes=("cohorte", "nunique"))
    g["retencion"] = g.activos / g.clientes
    g["ingreso_cliente_mes"] = g.ingreso / g.clientes
    return g.reset_index()


def payback_empirico(matriz: pd.DataFrame, tam: pd.DataFrame) -> pd.DataFrame:
    """
    Por cohorte y canal, el primer mes de vida en que el ingreso neto
    acumulado por cliente cubre el CAC. Queda vacío si aún no lo cubre.
    """
    m = matriz.merge(tam[["cohorte", "canal", "cac"]], on=["cohorte", "canal"], how="inner")
    m = m[m.cac > 0]
    cubre = m[m.ingreso_acum_cliente >= m.cac].groupby(["cohorte", "canal"]).k.min().rename("mes_payback")
    ult = m.groupby(["cohorte", "canal"]).agg(meses_observados=("k", "max"),
                                             ingreso_acum=("ingreso_acum_cliente", "last"),
                                             cac=("cac", "first"))
    out = ult.join(cubre).reset_index()
    out["cubierto_pct"] = out.ingreso_acum / out.cac
    return out


def ltv_empirico(matriz: pd.DataFrame, meses: int = 12) -> pd.DataFrame:
    """Ingreso acumulado por cliente en los primeros `meses` meses, solo cohortes que ya los cumplieron."""
    m = matriz[matriz.k == meses - 1]
    g = m.groupby("canal").apply(
        lambda d: pd.Series({"ltv_real": (d.ingreso_acum_cliente * d.clientes).sum() / d.clientes.sum(),
                             "cohortes": d.cohorte.nunique(), "clientes": d.clientes.sum(),
                             "primera": d.cohorte.min(), "ultima": d.cohorte.max()}),
        include_groups=False)
    return g.reset_index()


def ingreso_primer_dia(con, hasta: date) -> pd.DataFrame:
    """
    Por canal: qué parte de los activados genera ingreso en sus primeros 30 días
    y cuánto deja el primer día con ingreso. Sirve para pasar del modelo (que
    arranca en la primera transacción con ingreso) al cliente activado.
    """
    return con.execute("""
        WITH dias AS (
            SELECT id_cliente, fecha_hora::DATE AS dia, SUM(ingreso_neto) AS ingreso
            FROM transacciones GROUP BY ALL HAVING SUM(ingreso_neto) > 0
        ), primero AS (
            SELECT id_cliente, arg_min(ingreso, dia) AS ingreso, MIN(dia) AS dia
            FROM dias GROUP BY ALL
        )
        SELECT c.canal, COUNT(*) AS activados,
               AVG((p.dia IS NOT NULL AND p.dia <= c.fecha_activacion + 30)::INT) AS pct_con_ingreso,
               AVG(p.ingreso) AS ingreso_primer_dia
        FROM clientes c LEFT JOIN primero p USING (id_cliente)
        WHERE c.fecha_activacion IS NOT NULL AND c.fecha_activacion <= ?
        GROUP BY ALL ORDER BY c.canal
    """, [hasta]).df()


def mezcla_ingreso(con) -> pd.DataFrame:
    """Ingreso neto por tipo de transacción y canal."""
    return con.execute("""
        SELECT c.canal, t.tipo, COUNT(*) AS transacciones, SUM(t.ingreso_neto) AS ingreso
        FROM transacciones t JOIN clientes c USING (id_cliente)
        GROUP BY ALL ORDER BY c.canal, ingreso DESC
    """).df()
