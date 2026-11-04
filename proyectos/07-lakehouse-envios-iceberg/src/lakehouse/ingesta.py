"""Ingesta incremental lote a lote: archivos CDC -> bronce -> plata (estado, historial, cuarentena).

Cada tabla guarda en sus propiedades el último lote aplicado, en el mismo commit que los
datos. Si el proceso se cae a mitad de un lote, la siguiente corrida retoma cada tabla desde
su propia marca de agua y lo ya escrito no se duplica.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from functools import reduce

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThan, Or
from pyiceberg.table import Table

from .calendario import corte_de
from .catalogo import PROPIEDAD_LOTE, ultimo_lote
from .cdc import leer_lote, lotes_disponibles
from .contrato import TIPOS_DUCKDB, Contrato


@dataclass
class ResultadoLote:
    lote: str
    eventos: int = 0
    duplicados: int = 0
    tardios: int = 0
    descartados_lsn: int = 0
    cuarentena: int = 0
    insertados: int = 0
    actualizados: int = 0
    borrados: int = 0
    transiciones: int = 0
    filas_reescritas: int = 0
    dias_reescritos: int = 0
    rellenados: int = 0
    version_contrato: str = ""
    columnas_nuevas: list[str] = field(default_factory=list)
    no_declaradas: list[str] = field(default_factory=list)
    segundos: dict[str, float] = field(default_factory=dict)

    @property
    def tasa_cuarentena(self) -> float:
        nuevos = self.eventos - self.duplicados
        return self.cuarentena / nuevos if nuevos else 0.0

    def fila(self) -> dict:
        d = asdict(self)
        d["columnas_nuevas"] = ",".join(d["columnas_nuevas"])
        d["no_declaradas"] = ",".join(d["no_declaradas"])
        seg = d.pop("segundos")
        for k in ("bronce", "validar", "plata", "estados", "cuarentena"):
            d[f"seg_{k}"] = round(seg.get(k, 0.0), 3)
        return d


def _filtro_dias(columna: str, dias) -> object:
    """OR de rangos [día, día+1): coincide con la partición day() y deja borrar archivos enteros."""
    rangos = [And(GreaterThanOrEqual(columna, f"{d}T00:00:00"), LessThan(columna, f"{d + timedelta(days=1)}T00:00:00"))
              for d in sorted(dias)]
    return reduce(Or, rangos)


def _commit(t: Table, lote: str, datos: pa.Table | None, filtro=None) -> None:
    """Escribe datos y marca de agua en una sola transacción."""
    with t.transaction() as tx:
        if datos is not None and filtro is not None:
            tx.overwrite(datos, overwrite_filter=filtro, snapshot_properties={"lote": lote})
        elif datos is not None and datos.num_rows:
            tx.append(datos, snapshot_properties={"lote": lote})
        tx.set_properties({PROPIEDAD_LOTE: lote})


# ---------------------------------------------------------------------- bronce

def cargar_bronce(t: Table, lote: str, dir_cdc=None) -> int | None:
    """Agrega el lote tal cual llegó. Devuelve None si ya estaba cargado."""
    if ultimo_lote(t) >= lote:
        return None
    datos = leer_lote(lote, dir_cdc)
    _commit(t, lote, datos)
    return datos.num_rows


# ---------------------------------------------------------------------- plata

def _marcar(con: duckdb.DuckDBPyConnection, bronce: Table, contrato: Contrato, lote: str) -> None:
    """Deja en `marcados` los eventos del lote con su tipado, violaciones y si son duplicados o tardíos."""
    fecha = corte_de(lote).date()
    eventos = bronce.scan(row_filter=And(EqualTo("fecha_lote", fecha.isoformat()), EqualTo("lote", lote))).to_arrow()
    con.register("eventos", eventos)
    vistos = pa.table({"lsn": pa.array([], pa.int64())})
    if eventos.num_rows:
        lsn_min = pc.min(eventos["lsn"]).as_py()
        # el min/max de lsn por archivo deja leer solo los lotes recientes de bronce
        vistos = bronce.scan(row_filter=And(GreaterThanOrEqual("lsn", lsn_min), LessThan("lote", lote)),
                             selected_fields=("lsn",)).to_arrow()
    con.register("vistos", vistos)
    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE marcados AS
        SELECT v.*,
               v.lsn IN (SELECT lsn FROM vistos)
                 OR row_number() OVER (PARTITION BY v.lsn ORDER BY v.archivo, v.linea) > 1 AS duplicado,
               strftime(time_bucket(INTERVAL 6 HOUR, v.ts_commit) + INTERVAL 6 HOUR, '%Y-%m-%dT%H') < '{lote}'
                 AS tardio
        FROM ({contrato.sql_validacion('eventos')}) v
    """)


def _evolucionar(t: dict[str, Table], contrato: Contrato) -> tuple[list[str], int]:
    """Si la versión vigente del contrato trae columnas que plata no tiene, las agrega.

    Agregar una columna en Iceberg no reescribe datos: las filas viejas la leen como NULL.
    Después se rellena desde bronce: el evento que dejó cada fila en su estado actual (`_lsn`)
    ya traía la columna si salió de origen después del ALTER.
    """
    plata = t["plata"]
    nuevas = [c for c in contrato.activas() if c not in plata.schema().column_names]
    if not nuevas:
        return [], 0
    with plata.update_schema() as u:
        u.union_by_name(contrato.esquema())
    plata.refresh()
    con = duckdb.connect()
    con.register("plata", plata.scan().to_arrow())
    con.register("bronce", t["bronce"].scan(selected_fields=("lsn", "despues")).to_arrow())
    tipos = {c: TIPOS_DUCKDB[contrato.columnas[c].tipo] for c in nuevas}
    reemplazos = ", ".join(
        f"COALESCE(p.{c}, TRY_CAST(json_extract_string(b.despues, '$.{c}') AS {tipos[c]})) AS {c}" for c in nuevas)
    cond = " OR ".join(f"json_extract_string(b.despues, '$.{c}') IS NOT NULL" for c in nuevas)
    con.sql(f"""
        CREATE TEMP TABLE rellenos AS
        SELECT p.* REPLACE ({reemplazos})
        FROM plata p JOIN bronce b ON b.lsn = p._lsn
        WHERE {cond}
    """)
    dias = [d for (d,) in con.sql(f"SELECT DISTINCT CAST({contrato.particion} AS DATE) FROM rellenos").fetchall()]
    if not dias:
        return nuevas, 0
    n = con.sql("SELECT COUNT(*) FROM rellenos").fetchall()[0][0]
    esquema = plata.schema().as_arrow()
    filtro = _filtro_dias(contrato.particion, dias)
    datos = con.sql(f"""
        SELECT {', '.join(esquema.names)} FROM (
          SELECT * FROM rellenos
          UNION ALL BY NAME
          SELECT p.* FROM plata p ANTI JOIN rellenos USING (id_envio)
          WHERE CAST(p.{contrato.particion} AS DATE) IN
                (SELECT DISTINCT CAST({contrato.particion} AS DATE) FROM rellenos)
        ) ORDER BY id_envio
    """).to_arrow_table().cast(esquema)
    # sin tocar la marca de agua: si el proceso cae aquí, el lote se vuelve a aplicar entero
    with plata.transaction() as tx:
        tx.overwrite(datos, overwrite_filter=filtro, snapshot_properties={"operacion": "rellenar"})
    return nuevas, n


def _aplicar_estado(plata: Table, contrato: Contrato, con, lote: str, r: ResultadoLote) -> None:
    """Upsert copy-on-write: se reescriben solo los días de registro que el lote toca.

    Gana el evento con lsn más alto. Un evento tardío con lsn menor al que ya está en plata
    se descarta: si se aplicara, el envío volvería a un estado viejo.
    """
    columnas = [c for c in plata.schema().column_names if not c.startswith("_")]
    sel = ", ".join(columnas)
    con.sql(f"""
        CREATE OR REPLACE TEMP TABLE entrantes AS
        SELECT {sel}, lsn AS _lsn, lote AS _lote, op
        FROM marcados WHERE NOT duplicado AND len(violaciones) = 0
        QUALIFY row_number() OVER (PARTITION BY id_envio ORDER BY lsn DESC) = 1
    """)
    dias = [d for (d,) in con.sql(
        f"SELECT DISTINCT CAST({contrato.particion} AS DATE) FROM entrantes").fetchall()]
    if not dias:
        _commit(plata, lote, None)
        return
    filtro = _filtro_dias(contrato.particion, dias)
    actual = plata.scan(row_filter=filtro).to_arrow()
    con.register("actual", actual)
    n = con.sql("""
        SELECT COUNT(*) FILTER (WHERE a.id_envio IS NULL AND e.op <> 'd'),
               COUNT(*) FILTER (WHERE a.id_envio IS NOT NULL AND e._lsn > a._lsn AND e.op <> 'd'),
               COUNT(*) FILTER (WHERE a.id_envio IS NOT NULL AND e._lsn > a._lsn AND e.op = 'd'),
               COUNT(*) FILTER (WHERE a.id_envio IS NOT NULL AND e._lsn <= a._lsn)
        FROM entrantes e LEFT JOIN actual a USING (id_envio)
    """).fetchall()[0]
    r.insertados, r.actualizados, r.borrados, r.descartados_lsn = n
    esquema = plata.schema().as_arrow()
    nuevo = con.sql(f"""
        SELECT {', '.join(esquema.names)} FROM (
          SELECT * FROM entrantes
          UNION ALL BY NAME
          SELECT *, 'actual' AS op FROM actual
        )
        QUALIFY row_number() OVER (PARTITION BY id_envio ORDER BY _lsn DESC) = 1 AND op <> 'd'
        ORDER BY id_envio
    """).to_arrow_table().cast(esquema)
    r.filas_reescritas, r.dias_reescritos = nuevo.num_rows, len(dias)
    _commit(plata, lote, nuevo, filtro)


def _aplicar_historial(estados: Table, con, lote: str, r: ResultadoLote) -> None:
    datos = con.sql("""
        SELECT id_envio, estado,
               CASE WHEN estado = 'entregado' THEN COALESCE(entregado_en, actualizado_en)
                    ELSE actualizado_en END AS desde,
               lsn, lote
        FROM marcados
        WHERE NOT duplicado AND valido_historial AND op <> 'd'
          AND (op = 'c' OR estado IS DISTINCT FROM estado_antes)
        ORDER BY id_envio, lsn
    """).to_arrow_table().cast(estados.schema().as_arrow())
    r.transiciones = datos.num_rows
    _commit(estados, lote, datos)


def _aplicar_cuarentena(cuarentena: Table, con, lote: str, r: ResultadoLote) -> None:
    datos = con.sql("""
        SELECT lote, lsn, op, id_envio, violaciones, valido_historial AS en_historial, despues, fecha_lote
        FROM marcados WHERE NOT duplicado AND len(violaciones) > 0
    """).to_arrow_table().cast(cuarentena.schema().as_arrow())
    _commit(cuarentena, lote, datos)


def procesar_lote(t: dict[str, Table], contrato: Contrato, lote: str, dir_cdc=None) -> ResultadoLote:
    r = ResultadoLote(lote)
    contrato = contrato.vigente(corte_de(lote).date())
    r.version_contrato = contrato.version
    t0 = time.perf_counter()
    cargar_bronce(t["bronce"], lote, dir_cdc)
    r.segundos["bronce"] = time.perf_counter() - t0

    pendientes = {k: ultimo_lote(t[k]) < lote for k in ("plata", "estados", "cuarentena")}
    if not any(pendientes.values()):
        return r
    con = duckdb.connect()
    t0 = time.perf_counter()
    _marcar(con, t["bronce"], contrato, lote)
    r.eventos, r.duplicados, r.tardios, r.cuarentena = con.sql("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE duplicado), COUNT(*) FILTER (WHERE tardio AND NOT duplicado),
               COUNT(*) FILTER (WHERE NOT duplicado AND len(violaciones) > 0)
        FROM marcados""").fetchall()[0]
    r.no_declaradas = [c for (c, *_) in con.sql(contrato.sql_no_declaradas("marcados")).fetchall()]
    r.segundos["validar"] = time.perf_counter() - t0

    if pendientes["plata"]:
        t0 = time.perf_counter()
        r.columnas_nuevas, r.rellenados = _evolucionar(t, contrato)
        _aplicar_estado(t["plata"], contrato, con, lote, r)
        r.segundos["plata"] = time.perf_counter() - t0
    if pendientes["estados"]:
        t0 = time.perf_counter()
        _aplicar_historial(t["estados"], con, lote, r)
        r.segundos["estados"] = time.perf_counter() - t0
    if pendientes["cuarentena"]:
        t0 = time.perf_counter()
        _aplicar_cuarentena(t["cuarentena"], con, lote, r)
        r.segundos["cuarentena"] = time.perf_counter() - t0
    con.close()
    return r


def lotes_pendientes(t: dict[str, Table], dir_cdc=None, hasta: str | None = None) -> list[str]:
    """Lotes en disco posteriores a la marca de agua más atrasada de las tablas de ingesta."""
    marca = min(ultimo_lote(t[k]) for k in ("bronce", "plata", "estados", "cuarentena"))
    return [x for x in lotes_disponibles(dir_cdc) if x > marca and (hasta is None or x <= hasta)]
