"""Conciliación de plata contra el origen y comparación con aplicar el CDC "a la mala".

El origen final (`datos/origen/envios.parquet`) hace las veces del `SELECT` de control que
se le corre a la base transaccional: cuántos envíos hay y si cada columna coincide.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from pyiceberg.table import Table

from .contrato import Contrato
from .rutas import ruta_origen


def _con(plata: Table, origen: Path | None, contrato: Contrato) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("plata", plata.scan().to_arrow())
    o = pd.read_parquet(origen or ruta_origen())
    for c in contrato.activas():
        if c not in o:
            o[c] = None
    con.register("origen", o)
    return con


def conciliar(plata: Table, cuarentena: Table, contrato: Contrato, origen: Path | None = None) -> dict:
    """Envíos que faltan o sobran en plata y columnas que no coinciden con el origen."""
    con = _con(plata, origen, contrato)
    con.register("cuarentena", cuarentena.scan(selected_fields=("id_envio", "violaciones")).to_arrow())
    cols = [c for c in contrato.activas() if c != contrato.clave and c in plata.schema().column_names]
    conteos = con.sql("""
        SELECT (SELECT COUNT(*) FROM origen), (SELECT COUNT(*) FROM plata),
               (SELECT COUNT(*) FROM origen o ANTI JOIN plata p USING (id_envio)),
               (SELECT COUNT(*) FROM plata p ANTI JOIN origen o USING (id_envio)),
               (SELECT COUNT(*) FROM origen o ANTI JOIN plata p USING (id_envio)
                 SEMI JOIN cuarentena q USING (id_envio))
    """).fetchall()[0]
    difs = con.sql(f"""
        SELECT {', '.join(f'COUNT(*) FILTER (WHERE o.{c} IS DISTINCT FROM p.{c}) AS {c}' for c in cols)}
        FROM origen o JOIN plata p USING (id_envio)
    """).df().iloc[0]
    motivos = con.sql("""
        SELECT v AS regla, COUNT(DISTINCT id_envio) AS envios
        FROM (SELECT q.id_envio, unnest(q.violaciones) AS v
              FROM cuarentena q ANTI JOIN plata p USING (id_envio))
        GROUP BY 1 ORDER BY 2 DESC
    """).df()
    return {
        "origen": conteos[0], "plata": conteos[1], "faltan_en_plata": conteos[2], "sobran_en_plata": conteos[3],
        "faltan_explicados_por_cuarentena": conteos[4],
        "columnas_distintas": {c: int(n) for c, n in difs.items() if n},
        "motivos_faltantes": motivos,
    }


def ingenuo(bronce: Table, plata: Table, contrato: Contrato, origen: Path | None = None) -> dict:
    """Aplica el CDC en el orden en que llegó, sin mirar el lsn ni el contrato, y lo compara.

    Es lo que hace un `MERGE` que toma la última fila de cada lote como la buena.
    """
    con = _con(plata, origen, contrato)
    con.register("bronce", bronce.scan(selected_fields=("lote", "archivo", "linea", "lsn", "op", "id_envio",
                                                         "despues")).to_arrow())
    con.sql("""
        CREATE TEMP TABLE a_la_mala AS
        SELECT id_envio, op, json_extract_string(despues, '$.estado') AS estado,
               TRY_CAST(json_extract_string(despues, '$.entregado_en') AS TIMESTAMP) AS entregado_en
        FROM bronce
        QUALIFY row_number() OVER (PARTITION BY id_envio ORDER BY lote DESC, archivo DESC, linea DESC) = 1
    """)
    r = con.sql("""
        SELECT COUNT(*) FILTER (WHERE m.op <> 'd' AND m.estado IS DISTINCT FROM o.estado),
               COUNT(*) FILTER (WHERE m.op <> 'd' AND o.estado = 'entregado' AND m.estado <> 'entregado'),
               (SELECT COUNT(*) FROM origen o ANTI JOIN a_la_mala m USING (id_envio)),
               COUNT(*) FILTER (WHERE m.op <> 'd' AND p.estado IS DISTINCT FROM o.estado AND p.id_envio IS NOT NULL),
               (SELECT COUNT(*) FROM a_la_mala m ANTI JOIN origen o USING (id_envio) WHERE m.op <> 'd')
        FROM origen o JOIN a_la_mala m USING (id_envio) LEFT JOIN plata p USING (id_envio)
    """).fetchall()[0]
    cruce = con.sql("""
        SELECT o.estado AS en_origen, m.estado AS a_la_mala, COUNT(*) AS envios
        FROM origen o JOIN a_la_mala m USING (id_envio)
        WHERE m.op <> 'd' AND m.estado IS DISTINCT FROM o.estado
        GROUP BY ALL ORDER BY 3 DESC
    """).df()
    return {"estado_distinto": r[0], "entregados_que_no_figuran": r[1], "borrados_que_reaparecen": r[4],
            "faltan": r[2], "plata_estado_distinto": r[3], "cruce": cruce}
