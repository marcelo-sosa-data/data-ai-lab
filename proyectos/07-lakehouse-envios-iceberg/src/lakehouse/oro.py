"""Capa oro: cumplimiento de la promesa de entrega por día, zona y servicio.

Se recalcula en el corte de las 06:00, el que mira Operaciones en la reunión de la mañana,
y cada snapshot queda con un tag `corte-AAAA-MM-DD`. Con eso se puede ver qué decía el
tablero cualquier mañana, aunque después hayan llegado entregas sincronizadas tarde.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd
import pyarrow as pa
from pyiceberg.expressions import And, GreaterThanOrEqual, LessThan
from pyiceberg.table import Table

from .calendario import corte_de
from .catalogo import PROPIEDAD_LOTE
from .rutas import RAIZ

VENTANA_DIAS = 35  # promesas más antiguas ya no se recalculan
HORA_CORTE_ORO = 6

SQL_ORO = """
SELECT ? AS corte, e.fecha_promesa, d.zona, e.servicio,
       COUNT(*) AS comprometidos,
       COUNT(*) FILTER (WHERE e.estado = 'entregado') AS entregados,
       COUNT(*) FILTER (WHERE e.estado = 'entregado' AND CAST(e.entregado_en AS DATE) <= e.fecha_promesa) AS a_tiempo,
       COUNT(*) FILTER (WHERE e.intentos >= 1) AS intentados,
       COUNT(*) FILTER (WHERE (e.estado = 'entregado' AND e.intentos > 1)
                         OR e.estado IN ('intento_fallido', 'devuelto')) AS con_intento_fallido,
       COUNT(*) FILTER (WHERE e.estado = 'devuelto') AS devueltos,
       COUNT(*) FILTER (WHERE e.estado NOT IN ('entregado', 'devuelto')) AS pendientes
FROM envios e JOIN distritos d USING (distrito)
WHERE e.estado <> 'cancelado' AND e.fecha_promesa >= ? AND e.fecha_promesa < ?
GROUP BY ALL
ORDER BY 2, 3, 4
"""


def distritos() -> pd.DataFrame:
    return pd.read_csv(RAIZ / "referencia" / "distritos.csv")


def tag_corte(lote: str) -> str:
    return f"corte-{corte_de(lote).date()}"


def es_corte_oro(lote: str) -> bool:
    return corte_de(lote).hour == HORA_CORTE_ORO


def calcular(plata: Table, lote: str, snapshot_id: int | None = None) -> pd.DataFrame:
    """Indicadores para las promesas de los últimos 35 días ya cerrados al corte."""
    hoy = corte_de(lote).date()
    desde, hasta = hoy - timedelta(days=VENTANA_DIAS), hoy
    envios = plata.scan(row_filter=And(GreaterThanOrEqual("fecha_promesa", desde.isoformat()),
                                       LessThan("fecha_promesa", hasta.isoformat())),
                        selected_fields=("distrito", "servicio", "estado", "intentos", "entregado_en",
                                         "fecha_promesa"),
                        snapshot_id=snapshot_id).to_arrow()
    con = duckdb.connect()
    con.register("envios", envios)
    con.register("distritos", distritos())
    return con.execute(SQL_ORO, [lote, desde, hasta]).df()


def publicar(oro: Table, plata: Table, lote: str) -> int:
    """Reescribe la ventana de 35 días, etiqueta el snapshot y devuelve cuántas filas escribió."""
    df = calcular(plata, lote)
    hoy = corte_de(lote).date()
    desde = hoy - timedelta(days=VENTANA_DIAS)
    datos = pa.Table.from_pandas(df, preserve_index=False).cast(oro.schema().as_arrow())
    with oro.transaction() as tx:
        tx.overwrite(datos, overwrite_filter=GreaterThanOrEqual("fecha_promesa", desde.isoformat()),
                     snapshot_properties={"lote": lote})
        tx.set_properties({PROPIEDAD_LOTE: lote})
    oro.refresh()
    oro.manage_snapshots().create_tag(oro.current_snapshot().snapshot_id, tag_corte(lote)).commit()
    return datos.num_rows


def cortes(oro: Table) -> dict[date, int]:
    """Fecha de cada corte etiquetado -> snapshot."""
    oro.refresh()
    return {date.fromisoformat(n.removeprefix("corte-")): ref.snapshot_id
            for n, ref in oro.refs().items() if n.startswith("corte-")}


def indicadores(df: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """OTD = entregados a tiempo / comprometidos.

    Primer intento = de los que salieron a ruta, los que nunca tuvieron un intento fallido.
    """
    g = df.groupby(por or ["fecha_promesa"], as_index=False)[
        ["comprometidos", "entregados", "a_tiempo", "intentados", "con_intento_fallido", "devueltos",
         "pendientes"]].sum()
    g["otd"] = g["a_tiempo"] / g["comprometidos"]
    g["primer_intento"] = 1 - g["con_intento_fallido"] / g["intentados"].where(g["intentados"] > 0)
    return g
