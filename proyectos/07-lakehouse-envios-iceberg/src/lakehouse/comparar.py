"""Compara el upsert por partición de este proyecto con `Table.upsert` de pyiceberg.

Las dos variantes reciben los mismos eventos ya validados y deduplicados de cada lote; se
mide solo el paso que escribe plata.envios. `Table.upsert` busca las claves en toda la
tabla, así que su tiempo crece con el tamaño de la tabla; el upsert por partición solo lee
los días de registro que el lote toca.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
from pyiceberg.expressions import In

from . import catalogo
from .calendario import corte_de
from .cdc import lotes_disponibles
from .contrato import Contrato
from .ingesta import _marcar, procesar_lote


def comparar_upsert(contrato: Contrato, dir_trabajo: Path, lotes: int = 84, dir_cdc=None) -> pd.DataFrame:
    lista = lotes_disponibles(dir_cdc)[:lotes]
    c0 = contrato.vigente(corte_de(lista[0]).date())
    a = catalogo.crear_tablas(catalogo.abrir(Path(dir_trabajo) / "particion"), c0)
    cat_b = catalogo.abrir(Path(dir_trabajo) / "upsert")
    cat_b.create_namespace_if_not_exists("plata")
    b = cat_b.create_table("plata.envios", a["plata"].schema(), partition_spec=a["plata"].spec())
    filas = []
    for lote in lista:
        c = contrato.vigente(corte_de(lote).date())
        r = procesar_lote(a, c, lote, dir_cdc)
        con = duckdb.connect()
        _marcar(con, a["bronce"], c, lote)
        cols = ", ".join(n for n in b.schema().column_names if not n.startswith("_"))
        entrantes = con.sql(f"""
            SELECT {cols}, lsn AS _lsn, lote AS _lote, op FROM marcados
            WHERE NOT duplicado AND len(violaciones) = 0
            QUALIFY row_number() OVER (PARTITION BY id_envio ORDER BY lsn DESC) = 1
        """).df()
        t0 = time.perf_counter()
        vivos = entrantes[entrantes["op"] != "d"].drop(columns="op")
        if len(vivos):
            b.upsert(pa.Table.from_pandas(vivos, preserve_index=False).cast(b.schema().as_arrow()),
                     join_cols=["id_envio"])
        borrar = entrantes.loc[entrantes["op"] == "d", "id_envio"].tolist()
        if borrar:
            b.delete(In("id_envio", borrar))
        seg_b = time.perf_counter() - t0
        filas.append({"lote": lote, "entrantes": len(entrantes),
                      "filas_tabla": a["plata"].scan(selected_fields=("id_envio",)).to_arrow().num_rows,
                      "seg_particion": r.segundos.get("plata", 0.0), "seg_upsert": seg_b})
    return pd.DataFrame(filas)
