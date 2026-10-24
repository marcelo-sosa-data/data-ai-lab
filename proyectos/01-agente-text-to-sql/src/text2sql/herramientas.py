"""Herramientas que el modelo puede usar y cómo se ejecutan."""

from __future__ import annotations

import json

from .db import BaseDatos, _a_json

# Filas que se le devuelven al modelo. La consulta puede traer más
# (hasta max_filas), pero el modelo no necesita ver 200 filas para responder.
FILAS_AL_MODELO = 50

_HERRAMIENTAS = [
    {
        "name": "listar_tablas",
        "description": "Lista las tablas de la base con su descripción y número aproximado de filas.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "describir_tabla",
        "description": (
            "Devuelve las columnas de una tabla (tipo, descripción y, si es texto con pocos "
            "valores, la lista de valores posibles) y 3 filas de ejemplo."
        ),
        "parameters": {
            "type": "object",
            "properties": {"tabla": {"type": "string", "description": "Nombre de la tabla"}},
            "required": ["tabla"],
        },
    },
    {
        "name": "ejecutar_sql",
        "description": (
            "Ejecuta una consulta SELECT en DuckDB y devuelve columnas y filas. "
            "Solo lectura. Si la consulta falla, devuelve el error para que lo corrijas."
        ),
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "Consulta SELECT en dialecto DuckDB"}},
            "required": ["sql"],
        },
    },
    {
        "name": "responder",
        "description": "Entrega la respuesta final al usuario. Úsala una sola vez, al final.",
        "parameters": {
            "type": "object",
            "properties": {
                "respuesta": {
                    "type": "string",
                    "description": "Respuesta en español, breve, con las cifras y los supuestos usados",
                },
                "sql": {
                    "type": "string",
                    "description": "Consulta SQL final que sustenta la respuesta",
                },
            },
            "required": ["respuesta", "sql"],
        },
    },
]

# formato de tools de chat completions
DEFINICIONES = [{"type": "function", "function": h} for h in _HERRAMIENTAS]


def ejecutar_herramienta(db: BaseDatos, nombre: str, entrada: dict) -> tuple[str, bool]:
    """Devuelve (contenido para el modelo, es_error)."""
    if nombre == "listar_tablas":
        return json.dumps(db.listar_tablas(), ensure_ascii=False), False

    if nombre == "describir_tabla":
        info = db.describir_tabla(entrada.get("tabla", ""))
        return json.dumps(info, ensure_ascii=False, default=str), "error" in info

    if nombre == "ejecutar_sql":
        r = db.ejecutar(entrada.get("sql", ""))
        if not r.ok:
            return f"ERROR: {r.error}", True
        filas = [[_a_json(v) for v in f] for f in r.filas[:FILAS_AL_MODELO]]
        salida = {
            "columnas": r.columnas,
            "filas": filas,
            "total_filas": len(r.filas),
        }
        if len(r.filas) > FILAS_AL_MODELO or r.truncado:
            salida["nota"] = (f"Se muestran {len(filas)} filas. "
                              "Agrega filtros o agregaciones si necesitas ver todo.")
        return json.dumps(salida, ensure_ascii=False, default=str), False

    return f"ERROR: herramienta desconocida '{nombre}'", True
