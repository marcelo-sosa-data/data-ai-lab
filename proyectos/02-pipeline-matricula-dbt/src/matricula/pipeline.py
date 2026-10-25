"""
Corre dbt desde Python (dbtRunner) y guarda un registro de cada corrida.

Cada `build` deja dos tablas en el schema `auditoria` de la misma base:
  - corridas: una fila por corrida (cuándo, cuánto demoró, cuántos tests pasaron)
  - resultados: el detalle de cada modelo y test de la última corrida
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from .rutas import DIR_DBT, leer_manifiesto, ruta_db, ruta_raw

TIPOS = {"model": "modelo", "test": "test", "unit_test": "test unitario", "seed": "seed"}


@dataclass
class ResultadoNodo:
    nombre: str
    tipo: str
    estado: str          # success, pass, warn, fail, error, skipped
    segundos: float
    mensaje: str = ""
    filas: int | None = None


@dataclass
class ResultadoBuild:
    comando: str
    nodos: list[ResultadoNodo] = field(default_factory=list)
    segundos: float = 0.0
    error: str | None = None

    def contar(self, tipo: str, *estados: str) -> int:
        return sum(1 for n in self.nodos if n.tipo == tipo and n.estado in estados)

    @property
    def fallas(self) -> list[ResultadoNodo]:
        return [n for n in self.nodos if n.estado in ("fail", "error")]

    @property
    def avisos(self) -> list[ResultadoNodo]:
        return [n for n in self.nodos if n.estado == "warn"]

    @property
    def exito(self) -> bool:
        return self.error is None and not self.fallas


def _entorno(raw: Path, db: Path) -> None:
    # profiles.yml y las fuentes leen estas variables
    os.environ["MATRICULA_RAW"] = str(raw)
    os.environ["MATRICULA_DB"] = str(db)


def _liberar_duckdb() -> None:
    """dbt-duckdb deja abierta la base al terminar. Si no se cierra, el mismo proceso
    no puede volver a abrirla en modo solo lectura (la app, los tests)."""
    try:
        from dbt.adapters.duckdb.connections import DuckDBConnectionManager as Gestor
    except ImportError:
        return
    with Gestor._LOCK:
        if Gestor._ENV is not None:
            try:
                Gestor._ENV.close()
            finally:
                Gestor._ENV = None


def correr_dbt(comando: str = "build", raw: Path | None = None, db: Path | None = None,
               full_refresh: bool = False, extra: list[str] | None = None,
               registrar: bool = True) -> ResultadoBuild:
    """Ejecuta un comando de dbt (build, run, test, seed) contra el export indicado."""
    from dbt.cli.main import dbtRunner

    raw = Path(raw or ruta_raw()).resolve()
    db = Path(db or ruta_db()).resolve()
    db.parent.mkdir(parents=True, exist_ok=True)
    corte = leer_manifiesto(raw)["corte"]
    _entorno(raw, db)

    destino = db.parent / f".dbt_{db.stem}"
    args = [
        comando,
        "--project-dir", str(DIR_DBT),
        "--profiles-dir", str(DIR_DBT),
        "--target-path", str(destino / "target"),
        "--log-path", str(destino / "logs"),
        "--vars", json.dumps({"fecha_corte": corte}),
        "--quiet",
    ]
    if full_refresh:
        args.append("--full-refresh")
    args += extra or []

    inicio = time.perf_counter()
    try:
        res = dbtRunner().invoke(args)
    finally:
        _liberar_duckdb()
    salida = ResultadoBuild(comando=" ".join([comando] + (["--full-refresh"] if full_refresh else []) + (extra or [])))
    salida.segundos = round(time.perf_counter() - inicio, 2)

    if res.exception is not None:
        salida.error = str(res.exception)
    resultados = getattr(res.result, "results", None) or []
    for r in resultados:
        nodo = r.node
        salida.nodos.append(ResultadoNodo(
            nombre=nodo.name,
            tipo=TIPOS.get(str(nodo.resource_type), str(nodo.resource_type)),
            estado=str(r.status),
            segundos=round(r.execution_time or 0.0, 3),
            mensaje=(r.message or "") if str(r.status) in ("fail", "error", "warn") else "",
            filas=r.failures,
        ))
    if not res.success and salida.error is None and not salida.fallas:
        salida.error = "dbt terminó con error"

    if registrar and comando == "build" and resultados:
        registrar_corrida(salida, db)
    return salida


def registrar_corrida(res: ResultadoBuild, db: Path) -> None:
    con = duckdb.connect(str(db))
    try:
        con.execute("create schema if not exists auditoria")
        con.execute("""
            create table if not exists auditoria.corridas (
                fecha timestamp, comando varchar, segundos double, modelos integer,
                tests_ok integer, tests_warn integer, tests_error integer, exito boolean)
        """)
        tests = ("test", "test unitario")
        con.execute(
            "insert into auditoria.corridas values (?, ?, ?, ?, ?, ?, ?, ?)",
            [datetime.now().replace(microsecond=0), res.comando, res.segundos,
             res.contar("modelo", "success"),
             sum(res.contar(t, "pass") for t in tests),
             sum(res.contar(t, "warn") for t in tests),
             sum(res.contar(t, "fail", "error") for t in tests),
             res.exito],
        )
        con.execute("create or replace table auditoria.resultados as select * from (values (null::varchar, "
                    "null::varchar, null::varchar, null::double, null::varchar, null::bigint)) "
                    "t(nombre, tipo, estado, segundos, mensaje, filas) where false")
        con.executemany("insert into auditoria.resultados values (?, ?, ?, ?, ?, ?)",
                        [list(asdict(n).values()) for n in res.nodos])
    finally:
        con.close()
