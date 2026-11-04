"""Catálogo Iceberg (SQLite + archivos locales) y definición de las tablas del lakehouse.

Capas:
  bronce.cdc_envios      eventos tal como llegan, duplicados incluidos (append)
  plata.envios           estado actual por envío, esquema del contrato (copy-on-write por día)
  plata.estados_envio    cada cambio de estado con su hora (append)
  plata.cuarentena       eventos que rompen el contrato y por qué (append)
  oro.entregas_diarias   cumplimiento de promesa por día, zona y servicio (se reescribe cada mañana)
"""

from __future__ import annotations

import warnings
from pathlib import Path

from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.table.sorting import SortField, SortOrder
from pyiceberg.transforms import DayTransform, IdentityTransform, MonthTransform
from pyiceberg.types import (BooleanType, DateType, IntegerType, ListType, LongType,
                             NestedField, StringType, TimestampType)

from .contrato import Contrato
from .rutas import dir_lakehouse

# pyiceberg avisa cada vez que un overwrite no encuentra filas que borrar
warnings.filterwarnings("ignore", message="Delete operation did not match any records")

PROPIEDAD_LOTE = "kallpa.ultimo_lote"
PROPIEDADES = {  # sin esto queda un metadata.json por commit
    "write.metadata.delete-after-commit.enabled": "true",
    "write.metadata.previous-versions-max": "10",
}
F = NestedField

CONTROL_PLATA = [F(0, "_lsn", LongType(), required=True), F(0, "_lote", StringType(), required=True)]

ESQUEMA_BRONCE = Schema(
    F(1, "lote", StringType(), required=True),
    F(2, "archivo", StringType(), required=True),
    F(3, "linea", IntegerType(), required=True),
    F(4, "lsn", LongType(), required=True),
    F(5, "op", StringType(), required=True),
    F(6, "ts_commit", TimestampType(), required=True),
    F(7, "id_envio", LongType()),
    F(8, "antes", StringType()),
    F(9, "despues", StringType()),
    F(10, "fecha_lote", DateType(), required=True),
)

ESQUEMA_ESTADOS = Schema(
    F(1, "id_envio", LongType(), required=True),
    F(2, "estado", StringType(), required=True),
    F(3, "desde", TimestampType(), required=True),
    F(4, "lsn", LongType(), required=True),
    F(5, "lote", StringType(), required=True),
)

ESQUEMA_CUARENTENA = Schema(
    F(1, "lote", StringType(), required=True),
    F(2, "lsn", LongType(), required=True),
    F(3, "op", StringType(), required=True),
    F(4, "id_envio", LongType()),
    F(5, "violaciones", ListType(20, StringType(), element_required=True), required=True),
    F(6, "en_historial", BooleanType(), required=True),
    F(7, "despues", StringType()),
    F(8, "fecha_lote", DateType(), required=True),
)

ESQUEMA_ORO = Schema(
    F(1, "corte", StringType(), required=True),
    F(2, "fecha_promesa", DateType(), required=True),
    F(3, "zona", StringType(), required=True),
    F(4, "servicio", StringType(), required=True),
    F(5, "comprometidos", LongType(), required=True),
    F(6, "entregados", LongType(), required=True),
    F(7, "a_tiempo", LongType(), required=True),
    F(8, "intentados", LongType(), required=True),
    F(9, "con_intento_fallido", LongType(), required=True),
    F(10, "devueltos", LongType(), required=True),
    F(11, "pendientes", LongType(), required=True),
)


def abrir(directorio: Path | None = None) -> SqlCatalog:
    d = Path(directorio or dir_lakehouse()).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return SqlCatalog("kallpa", uri=f"sqlite:///{d / 'catalogo.db'}", warehouse=f"file://{d}")


def _crear(cat: SqlCatalog, nombre: str, esquema: Schema, particion: PartitionSpec,
           orden: SortOrder | None = None, propiedades: dict | None = None) -> Table:
    try:
        return cat.load_table(nombre)
    except NoSuchTableError:
        cat.create_namespace_if_not_exists(nombre.split(".")[0])
        return cat.create_table(nombre, esquema, partition_spec=particion,
                                sort_order=orden or SortOrder(), properties={**PROPIEDADES, **(propiedades or {})})


def _particion(esquema: Schema, columna: str, transformacion, nombre: str) -> PartitionSpec:
    return PartitionSpec(PartitionField(esquema.find_field(columna).field_id, 1000, transformacion, nombre))


def crear_tablas(cat: SqlCatalog, contrato: Contrato) -> dict[str, Table]:
    """Crea (si no existen) las cinco tablas. Plata toma su esquema del contrato."""
    plata = contrato.esquema(extra=CONTROL_PLATA)
    orden_id = lambda s: SortOrder(SortField(source_id=s.find_field("id_envio").field_id,  # noqa: E731
                                             transform=IdentityTransform()))
    return {
        "bronce": _crear(cat, "bronce.cdc_envios", ESQUEMA_BRONCE,
                         _particion(ESQUEMA_BRONCE, "fecha_lote", MonthTransform(), "mes_lote")),
        "plata": _crear(cat, "plata.envios", plata,
                        _particion(plata, contrato.particion, DayTransform(), "dia_registro"), orden_id(plata)),
        "estados": _crear(cat, "plata.estados_envio", ESQUEMA_ESTADOS,
                          _particion(ESQUEMA_ESTADOS, "desde", MonthTransform(), "mes"), orden_id(ESQUEMA_ESTADOS)),
        "cuarentena": _crear(cat, "plata.cuarentena", ESQUEMA_CUARENTENA,
                             _particion(ESQUEMA_CUARENTENA, "fecha_lote", MonthTransform(), "mes_lote")),
        "oro": _crear(cat, "oro.entregas_diarias", ESQUEMA_ORO,
                      _particion(ESQUEMA_ORO, "fecha_promesa", MonthTransform(), "mes_promesa")),
    }


def tablas(cat: SqlCatalog | None = None) -> dict[str, Table]:
    cat = cat or abrir()
    nombres = {"bronce": "bronce.cdc_envios", "plata": "plata.envios", "estados": "plata.estados_envio",
               "cuarentena": "plata.cuarentena", "oro": "oro.entregas_diarias"}
    return {k: cat.load_table(v) for k, v in nombres.items()}


def ultimo_lote(t: Table) -> str:
    """Marca de agua: el último lote aplicado, guardado en la tabla en el mismo commit que los datos."""
    t.refresh()
    return t.properties.get(PROPIEDAD_LOTE, "")
