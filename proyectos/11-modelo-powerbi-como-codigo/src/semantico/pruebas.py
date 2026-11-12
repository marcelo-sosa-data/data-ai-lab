"""
Pruebas de medidas: cada caso compara la medida DAX contra un SQL de referencia.

El SQL lo escribe quien conoce la definición del indicador, sin mirar el DAX.
Si las dos versiones dan lo mismo en todos los grupos, la medida hace lo que
dice su descripción; si no, la prueba muestra en qué grupos difieren.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml

from .dax import ErrorDAX
from .motor import Motor

TOLERANCIA = 1e-9


@dataclass
class Caso:
    id: str
    medida: str
    sql: str
    filtros: dict = field(default_factory=dict)
    por: str | None = None
    descripcion: str = ""


@dataclass
class ResultadoCaso:
    caso: Caso
    ok: bool
    esperado: dict = field(default_factory=dict)
    obtenido: dict = field(default_factory=dict)
    diferencias: list = field(default_factory=list)  # [(clave, esperado, obtenido)]
    error: str = ""
    segundos: float = 0.0


def cargar_casos(ruta: str | Path) -> list[Caso]:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    casos = [Caso(**d) for d in datos]
    ids = [c.id for c in casos]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise ValueError(f"Casos con id repetido: {sorted(repetidos)}")
    return casos


def conexion_sql(carpeta: str | Path) -> duckdb.DuckDBPyConnection:
    """DuckDB en memoria con una vista por cada Parquet de la carpeta."""
    con = duckdb.connect()
    for f in sorted(Path(carpeta).glob("*.parquet")):
        con.execute(f"CREATE VIEW {f.stem} AS SELECT * FROM read_parquet('{f.as_posix()}')")
    return con


def esperado_sql(con: duckdb.DuckDBPyConnection, caso: Caso) -> dict:
    rel = con.execute(caso.sql)
    columnas = [d[0] for d in rel.description]
    filas = rel.fetchall()
    if "clave" in columnas:
        ic, iv = columnas.index("clave"), columnas.index("valor")
        return {f[ic]: _num(f[iv]) for f in filas if f[iv] is not None}
    return {None: _num(f[0]) for f in filas if f[0] is not None}


def _num(v):
    return float(v) if v is not None and not isinstance(v, (str, bool)) else v


def comparar(esperado: dict, obtenido: dict, tol: float = TOLERANCIA) -> list:
    difs = []
    for k in sorted(set(esperado) | set(obtenido), key=str):
        e, o = esperado.get(k), obtenido.get(k)
        if e is None or o is None:
            if e is not o:
                difs.append((k, e, o))
            continue
        try:
            if not math.isclose(float(e), float(o), rel_tol=tol, abs_tol=tol):
                difs.append((k, e, o))
        except (TypeError, ValueError):
            if e != o:
                difs.append((k, e, o))
    return difs


def correr_caso(motor: Motor, con, caso: Caso) -> ResultadoCaso:
    t0 = time.perf_counter()
    try:
        esperado = esperado_sql(con, caso)
    except duckdb.Error as e:
        return ResultadoCaso(caso, False, error=f"El SQL de referencia falla: {e}")
    try:
        obtenido = motor.evaluar(caso.medida, caso.filtros, caso.por)
    except (ErrorDAX, KeyError) as e:
        return ResultadoCaso(caso, False, esperado, error=f"La medida no se pudo evaluar: {e}",
                             segundos=time.perf_counter() - t0)
    obtenido = {k: _num(v) for k, v in obtenido.items()}
    difs = comparar(esperado, obtenido)
    return ResultadoCaso(caso, not difs, esperado, obtenido, difs, segundos=time.perf_counter() - t0)


def correr(motor: Motor, casos: list[Caso], con) -> list[ResultadoCaso]:
    return [correr_caso(motor, con, c) for c in casos]


def medidas_sin_prueba(medidas, casos: list[Caso]) -> list[str]:
    probadas = {c.medida for c in casos}
    return sorted(m for m in medidas if m not in probadas)
