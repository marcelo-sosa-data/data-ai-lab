"""
Definiciones de Dagster: los assets del lakehouse, sus chequeos, un sensor que lanza una
corrida por cada lote nuevo y el mantenimiento semanal.

    dagster dev -m lakehouse.definiciones

Los assets llaman a las mismas funciones que la CLI (`ingesta`, `oro`, `mantenimiento`).
"""


from pathlib import Path

import duckdb
from dagster import (AssetCheckResult, AssetCheckSeverity, AssetCheckSpec, AssetExecutionContext, AssetKey,
                     AssetSelection, AssetSpec, Config, ConfigurableResource, DefaultScheduleStatus,
                     DefaultSensorStatus, Definitions, MaterializeResult, OpExecutionContext, RunRequest,
                     ScheduleDefinition, SensorEvaluationContext, SkipReason, asset, define_asset_job, job,
                     multi_asset, op, sensor)

from . import catalogo
from .bitacora import Bitacora
from .cdc import lotes_disponibles
from .contrato import Contrato
from .ingesta import cargar_bronce, lotes_pendientes, procesar_lote
from .oro import es_corte_oro, publicar
from .pipeline import mantenimiento, preparar
from .rutas import dir_datos, ruta_contrato

GRUPO = "kallpa"


class Lakehouse(ConfigurableResource):
    """Dónde están los archivos CDC, el catálogo y el contrato."""

    datos: str = str(dir_datos())
    contrato: str = str(ruta_contrato())

    @property
    def dir_cdc(self) -> Path:
        return Path(self.datos) / "cdc"

    def abrir(self):
        return preparar(Path(self.datos) / "lakehouse", Contrato.desde_yaml(Path(self.contrato)), self.dir_cdc)

    def bitacora(self) -> Bitacora:
        return Bitacora(Path(self.datos) / "bitacora.duckdb")


class Hasta(Config):
    """Último lote que procesa esta corrida (el sensor manda uno por corrida). Vacío: todos."""

    hasta: str = ""


def _hasta(config: Hasta) -> str | None:
    return config.hasta or None


@asset(group_name=GRUPO, key=AssetKey(["bronce", "cdc_envios"]), compute_kind="iceberg",
       description="Eventos del CDC tal como llegan, duplicados incluidos.")
def cdc_bronce(context: AssetExecutionContext, config: Hasta, lakehouse: Lakehouse) -> MaterializeResult:
    _, t = lakehouse.abrir()
    marca = catalogo.ultimo_lote(t["bronce"])
    nuevos = [x for x in lotes_disponibles(lakehouse.dir_cdc) if x > marca and (not config.hasta or x <= config.hasta)]
    eventos = sum(cargar_bronce(t["bronce"], x, lakehouse.dir_cdc) or 0 for x in nuevos)
    context.log.info(f"{len(nuevos)} lotes nuevos en bronce")
    return MaterializeResult(metadata={"lotes": len(nuevos), "eventos": eventos,
                                       "ultimo_lote": catalogo.ultimo_lote(t["bronce"])})


PLATA = [AssetKey(["plata", n]) for n in ("envios", "estados_envio", "cuarentena")]


@multi_asset(
    group_name=GRUPO, compute_kind="iceberg",
    specs=[AssetSpec(k, deps=[AssetKey(["bronce", "cdc_envios"])]) for k in PLATA],
    check_specs=[
        AssetCheckSpec("clave_unica", asset=PLATA[0], description="un registro por id_envio"),
        AssetCheckSpec("cuarentena_bajo_umbral", asset=PLATA[2],
                       description="ningún lote de la corrida supera el umbral del contrato"),
    ],
)
def plata(context: AssetExecutionContext, config: Hasta, lakehouse: Lakehouse):
    """Valida contra el contrato y aplica: estado actual, historial de estados y cuarentena."""
    contrato, t = lakehouse.abrir()
    res = [procesar_lote(t, contrato, x, lakehouse.dir_cdc)
           for x in lotes_pendientes(t, lakehouse.dir_cdc, _hasta(config))]
    for r in res:
        if r.columnas_nuevas:
            context.log.warning(f"{r.lote}: plata.envios agrega {r.columnas_nuevas}")
        if r.no_declaradas:
            context.log.warning(f"{r.lote}: columnas fuera del contrato {r.no_declaradas}")
    suma = lambda campo: sum(getattr(r, campo) for r in res)  # noqa: E731
    yield MaterializeResult(asset_key=PLATA[0], metadata={
        "lotes": len(res), "insertados": suma("insertados"), "actualizados": suma("actualizados"),
        "borrados": suma("borrados"), "ignorados_por_lsn": suma("descartados_lsn")})
    yield MaterializeResult(asset_key=PLATA[1], metadata={"transiciones": suma("transiciones")})
    yield MaterializeResult(asset_key=PLATA[2], metadata={"eventos": suma("cuarentena")})

    con = duckdb.connect()
    con.register("p", t["plata"].scan(selected_fields=("id_envio",)).to_arrow())
    repetidos = con.sql("SELECT COUNT(*) - COUNT(DISTINCT id_envio) FROM p").fetchall()[0][0]
    yield AssetCheckResult(check_name="clave_unica", asset_key=PLATA[0], passed=repetidos == 0,
                           metadata={"repetidos": int(repetidos)})
    altos = [r for r in res if r.tasa_cuarentena > contrato.umbral_cuarentena]
    peor = max(res, key=lambda r: r.tasa_cuarentena, default=None)
    yield AssetCheckResult(
        check_name="cuarentena_bajo_umbral", asset_key=PLATA[2], passed=not altos,
        severity=AssetCheckSeverity.WARN,
        metadata={"lotes_sobre_umbral": len(altos), "peor_lote": peor.lote if peor else "",
                  "peor_tasa": round(peor.tasa_cuarentena, 4) if peor else 0.0})


@asset(group_name=GRUPO, key=AssetKey(["oro", "entregas_diarias"]), deps=[PLATA[0]], compute_kind="duckdb",
       description="Cumplimiento de promesa por día, zona y servicio; se publica en el corte de las 06:00.")
def entregas_diarias(context: AssetExecutionContext, config: Hasta, lakehouse: Lakehouse) -> MaterializeResult:
    _, t = lakehouse.abrir()
    lote = catalogo.ultimo_lote(t["plata"])
    if not lote or not es_corte_oro(lote) or catalogo.ultimo_lote(t["oro"]) >= lote:
        return MaterializeResult(metadata={"publicado": False, "lote": lote})
    filas = publicar(t["oro"], t["plata"], lote)
    return MaterializeResult(metadata={"publicado": True, "lote": lote, "filas": filas})


ingesta = define_asset_job("ingesta", selection=AssetSelection.groups(GRUPO))


@sensor(job=ingesta, minimum_interval_seconds=300, default_status=DefaultSensorStatus.STOPPED)
def lotes_nuevos(context: SensorEvaluationContext, lakehouse: Lakehouse):
    """Una corrida por cada carpeta `lote=` nueva; el run_key evita lanzar dos veces el mismo lote."""
    _, t = lakehouse.abrir()
    pendientes = lotes_pendientes(t, lakehouse.dir_cdc)
    if not pendientes:
        return SkipReason("sin lotes nuevos")
    for lote in pendientes:
        cfg = {"config": {"hasta": lote}}
        yield RunRequest(run_key=lote, run_config={"ops": {"bronce__cdc_envios": cfg, "plata": cfg,
                                                           "oro__entregas_diarias": cfg}})


@op
def mantener_tablas(context: OpExecutionContext, lakehouse: Lakehouse) -> None:
    _, t = lakehouse.abrir()
    filas = mantenimiento(t, catalogo.ultimo_lote(t["bronce"]))
    lakehouse.bitacora().mantenimiento(filas)
    for f in filas:
        context.log.info(f"{f['tabla']}: {f['antes_archivos_datos']} -> {f['despues_archivos_datos']} archivos, "
                         f"{f['snapshots_expirados']} snapshots expirados, {f['huerfanos_borrados']} huérfanos")


@job
def mantenimiento_semanal():
    mantener_tablas()


defs = Definitions(
    assets=[cdc_bronce, plata, entregas_diarias],
    jobs=[ingesta, mantenimiento_semanal],
    sensors=[lotes_nuevos],
    schedules=[ScheduleDefinition(job=mantenimiento_semanal, cron_schedule="0 6 * * 0",
                                  execution_timezone="America/Lima", default_status=DefaultScheduleStatus.STOPPED)],
    resources={"lakehouse": Lakehouse()},
)
