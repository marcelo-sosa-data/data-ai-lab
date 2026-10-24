"""
Validación del SQL que genera el modelo antes de tocar la base.

La conexión ya es de solo lectura, pero eso no basta: en DuckDB un SELECT
puede leer archivos del servidor (read_csv('/etc/passwd')), ejecutar SQL
dinámico (query(...)) o leer variables de entorno (getenv). Por eso se
revisa el árbol sintáctico completo, no el texto con regex.

Reglas:
  1. Una sola sentencia.
  2. Solo SELECT (incluye WITH, UNION, INTERSECT, EXCEPT).
  3. Solo tablas de la lista permitida (o CTEs definidos en la misma consulta).
  4. Nada de funciones que lean archivos, entorno o ejecuten SQL dinámico.
  5. Si no trae LIMIT, se le agrega uno.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

FUNCIONES_BLOQUEADAS = {"getenv", "glob", "query", "query_table", "current_setting",
                        "load", "install", "system"}
PREFIJOS_BLOQUEADOS = ("read_", "parquet_", "sniff_", "duckdb_", "pragma_",
                       "iceberg_", "delta_", "sqlite_", "postgres_", "mysql_")


@dataclass
class ResultadoValidacion:
    ok: bool
    sql: str = ""
    motivo: str = ""


class SQLNoPermitido(ValueError):
    pass


def _nombre_funcion(f: exp.Func) -> str:
    return (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()


def validar_sql(sql: str, tablas_permitidas: set[str], limite: int = 200) -> ResultadoValidacion:
    try:
        return ResultadoValidacion(True, _validar(sql, tablas_permitidas, limite))
    except SQLNoPermitido as e:
        return ResultadoValidacion(False, motivo=str(e))


def _validar(sql: str, tablas_permitidas: set[str], limite: int) -> str:
    sql = (sql or "").strip().rstrip(";")
    if not sql:
        raise SQLNoPermitido("La consulta está vacía.")

    try:
        sentencias = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SQLNoPermitido(f"No se pudo interpretar el SQL: {str(e).splitlines()[0]}")

    if len(sentencias) != 1:
        raise SQLNoPermitido("Solo se permite una sentencia por consulta.")
    arbol = sentencias[0]

    if not isinstance(arbol, (exp.Select, exp.SetOperation)):
        raise SQLNoPermitido(
            f"Solo se permiten consultas SELECT (se recibió {type(arbol).__name__.upper()})."
        )

    # Ningún nodo de escritura escondido en subconsultas
    prohibidos = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
                  exp.Alter, exp.Command, exp.Merge, exp.Copy, exp.Set, exp.Pragma)
    for nodo in arbol.walk():
        if isinstance(nodo, prohibidos):
            raise SQLNoPermitido(f"Operación no permitida: {type(nodo).__name__.upper()}.")

    # Tablas: solo las permitidas o CTEs propios
    ctes = {c.alias_or_name.lower() for c in arbol.find_all(exp.CTE)}
    permitidas = {t.lower() for t in tablas_permitidas} | ctes
    for tabla in arbol.find_all(exp.Table):
        if not isinstance(tabla.this, exp.Identifier):
            raise SQLNoPermitido("No se permiten funciones de tabla en el FROM (por ejemplo read_csv).")
        if tabla.args.get("db") or tabla.args.get("catalog"):
            raise SQLNoPermitido(f"No se permite referenciar otros esquemas: {tabla.sql()}.")
        if tabla.name.lower() not in permitidas:
            raise SQLNoPermitido(
                f"La tabla '{tabla.name}' no existe o no está permitida. "
                f"Tablas disponibles: {', '.join(sorted(tablas_permitidas))}."
            )

    for f in arbol.find_all(exp.Func):
        nombre = _nombre_funcion(f)
        if nombre in FUNCIONES_BLOQUEADAS or nombre.startswith(PREFIJOS_BLOQUEADOS) \
                or nombre.endswith("_scan"):
            raise SQLNoPermitido(f"La función {nombre}() no está permitida.")

    if not arbol.args.get("limit"):
        if isinstance(arbol, exp.Select):
            arbol = arbol.limit(limite)
        else:
            arbol = exp.select("*").from_(arbol.subquery("t")).limit(limite)

    return arbol.sql(dialect="duckdb", pretty=True)
