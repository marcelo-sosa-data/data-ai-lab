"""Mantenimiento de las tablas: compactar archivos chicos, expirar snapshots y borrar huérfanos.

Una tabla que recibe un append cada 6 horas junta cientos de archivos de pocos KB y un
snapshot por commit. Leerla obliga a abrir todos esos archivos y el metadata.json crece con
cada snapshot. pyiceberg expira snapshots pero no borra los archivos que dejan de usarse,
así que eso se hace aquí.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pyarrow.compute as pc
from pyiceberg.expressions import And, GreaterThanOrEqual, LessThan
from pyiceberg.table import Table
from pyiceberg.transforms import DayTransform, MonthTransform

from .catalogo import PROPIEDAD_LOTE

ORDEN = {"bronce.cdc_envios": "lsn", "plata.cuarentena": "lsn", "oro.entregas_diarias": "fecha_promesa"}


@dataclass
class Estadisticas:
    tabla: str
    filas: int
    archivos_datos: int
    mb_datos: float
    manifiestos: int
    snapshots: int
    archivos_en_disco: int
    mb_en_disco: float
    kb_metadata_json: float
    seg_lectura: float

    def fila(self) -> dict:
        return asdict(self)


def _ruta(uri: str) -> Path:
    return Path(uri.removeprefix("file://"))


def estadisticas(t: Table, medir_lectura: bool = True) -> Estadisticas:
    t.refresh()
    archivos = t.inspect.files()
    raiz = _ruta(t.location())
    en_disco = [p for p in raiz.rglob("*") if p.is_file()]
    seg = filas = 0
    if medir_lectura:
        t0 = time.perf_counter()
        filas = t.scan().to_arrow().num_rows
        seg = time.perf_counter() - t0
    else:
        filas = int(pc.sum(archivos["record_count"]).as_py() or 0)
    return Estadisticas(
        tabla=".".join(t.name()),
        filas=filas, archivos_datos=archivos.num_rows,
        mb_datos=round((pc.sum(archivos["file_size_in_bytes"]).as_py() or 0) / 1e6, 2),
        manifiestos=t.inspect.manifests().num_rows, snapshots=len(t.snapshots()),
        archivos_en_disco=len(en_disco), mb_en_disco=round(sum(p.stat().st_size for p in en_disco) / 1e6, 2),
        kb_metadata_json=round(os.path.getsize(_ruta(t.metadata_location)) / 1e3, 1), seg_lectura=round(seg, 3),
    )


def _rango_particion(t: Table, valor) -> object:
    """Filtro sobre la columna fuente que cubre exactamente una partición mensual o diaria."""
    campo = t.spec().fields[0]
    col = t.schema().find_field(campo.source_id).name
    if isinstance(campo.transform, MonthTransform):
        a, m = divmod(int(valor), 12)
        ini = date(1970 + a, m + 1, 1)
        fin = date(ini.year + (ini.month == 12), ini.month % 12 + 1, 1)
    elif isinstance(campo.transform, DayTransform):
        ini = valor if isinstance(valor, date) else date.fromordinal(date(1970, 1, 1).toordinal() + int(valor))
        fin = date.fromordinal(ini.toordinal() + 1)
    else:
        raise ValueError(f"transformación no soportada: {campo.transform}")
    es_ts = "timestamp" in str(t.schema().find_field(col).field_type)
    a, b = (f"{ini}T00:00:00", f"{fin}T00:00:00") if es_ts else (ini.isoformat(), fin.isoformat())
    return And(GreaterThanOrEqual(col, a), LessThan(col, b))


def compactar(t: Table, minimo_archivos: int = 4) -> int:
    """Reescribe en un solo archivo, ordenado, cada partición con muchos archivos chicos.

    Devuelve cuántos archivos reemplazó. La marca de agua no cambia: los datos son los mismos.
    """
    t.refresh()
    archivos = t.inspect.files().to_pandas()
    if archivos.empty:
        return 0
    nombre_part = t.spec().fields[0].name
    archivos["p"] = archivos["partition"].map(lambda x: x[nombre_part])
    reemplazados = 0
    orden = ORDEN.get(".".join(t.name()), "id_envio")  # el resto, por id_envio
    lote = t.properties.get(PROPIEDAD_LOTE, "")
    for valor, grupo in archivos.groupby("p"):
        if len(grupo) < minimo_archivos:
            continue
        filtro = _rango_particion(t, valor)
        datos = t.scan(row_filter=filtro).to_arrow()
        datos = datos.sort_by([(orden, "ascending")])
        with t.transaction() as tx:
            tx.overwrite(datos, overwrite_filter=filtro, snapshot_properties={"lote": lote, "operacion": "compactar"})
        reemplazados += len(grupo)
    return reemplazados


def expirar(t: Table, conservar: int = 3) -> int:
    """Expira todo menos los últimos `conservar` snapshots y los que tienen un tag (cortes de oro).

    La simulación comprime cuatro meses en minutos, así que se conserva por cantidad y no por
    antigüedad como se haría en producción (`older_than`).
    """
    t.refresh()
    protegidos = {r.snapshot_id for r in t.refs().values()}
    ids = [s.snapshot_id for s in sorted(t.snapshots(), key=lambda s: s.timestamp_ms)]
    viejos = [i for i in ids[:-conservar] if i not in protegidos]
    if viejos:
        t.maintenance.expire_snapshots().by_ids(viejos).commit()
    return len(viejos)


def borrar_huerfanos(t: Table) -> int:
    """Borra archivos de datos y manifiestos que ningún snapshot vivo referencia.

    Solo es seguro con un único escritor: un commit en curso de otro proceso podría estar
    escribiendo archivos que todavía no aparecen en la metadata.
    """
    t.refresh()
    vivos = set(t.inspect.all_files()["file_path"].to_pylist())
    vivos |= set(t.inspect.all_manifests()["path"].to_pylist())
    vivos |= {s.manifest_list for s in t.snapshots()}
    vivos |= {t.metadata_location} | {e.metadata_file for e in t.metadata.metadata_log}
    vivos = {_ruta(v).resolve() for v in vivos}
    borrados = 0
    for p in _ruta(t.location()).rglob("*"):
        if p.is_file() and p.resolve() not in vivos and p.suffix in (".parquet", ".avro", ".json"):
            p.unlink()
            borrados += 1
    return borrados


def mantener(t: Table, minimo_archivos: int = 4, conservar: int = 3) -> dict:
    t0 = time.perf_counter()
    r = {"archivos_compactados": compactar(t, minimo_archivos), "snapshots_expirados": expirar(t, conservar)}
    r["huerfanos_borrados"] = borrar_huerfanos(t)
    r["segundos"] = round(time.perf_counter() - t0, 2)
    return r
