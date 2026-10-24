"""
Uso:
    python -m text2sql "¿Cuánto vendimos en agosto?"
    python -m text2sql --demo "¿Cuál es el ticket promedio de 2026?"
    python -m text2sql            # modo conversación
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .agente import AgenteTextToSQL, Resultado
from .db import BaseDatos, _a_json
from .llm import ModeloLLM, ModeloDemo

RAIZ = Path(__file__).parents[2]
consola = Console()


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ruta)
    except ImportError:
        pass


def crear_agente(demo: bool, ruta_db: Path, modelo: str | None = None) -> AgenteTextToSQL:
    db = BaseDatos(ruta_db)
    llm = ModeloDemo() if demo else ModeloLLM(modelo)
    return AgenteTextToSQL(llm, db)


def mostrar(res: Resultado, detalle: bool) -> None:
    if detalle:
        for i, p in enumerate(res.pasos, 1):
            color = "red" if p.error else "cyan"
            titulo = f"[{color}]Paso {i}: {p.herramienta}[/]"
            cuerpo = p.entrada.get("sql") or p.entrada.get("tabla") or ""
            salida = p.salida if len(p.salida) < 400 else p.salida[:400] + " ..."
            consola.print(titulo, f"[dim]{p.pensamiento}[/]" if p.pensamiento else "")
            if cuerpo:
                consola.print(f"  {cuerpo}")
            consola.print(f"  [dim]{salida}[/]")

    if res.sql:
        consola.print(Panel(Syntax(res.sql, "sql", theme="ansi_dark", word_wrap=True),
                            title="SQL", border_style="dim"))
    if res.filas:
        tabla = Table(show_lines=False, header_style="bold")
        for c in res.columnas:
            tabla.add_column(c)
        for f in res.filas[:15]:
            tabla.add_row(*[_formato(v) for v in f])
        if len(res.filas) > 15:
            tabla.caption = f"... {len(res.filas) - 15} filas más"
        consola.print(tabla)

    consola.print(Panel(res.respuesta or "(sin respuesta)", title="Respuesta",
                        border_style="green" if res.ok else "red"))
    consola.print(
        f"[dim]{len(res.pasos)} pasos · {res.consultas_fallidas} consultas corregidas · "
        f"{res.tokens_entrada:,} tokens entrada / {res.tokens_salida:,} salida · "
        f"{res.segundos:.1f} s[/]"
    )


def _formato(v) -> str:
    v = _a_json(v)
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def main() -> None:
    cargar_env()
    parser = argparse.ArgumentParser(prog="text2sql", description="Pregúntale a la base en español.")
    parser.add_argument("pregunta", nargs="?", help="Pregunta en lenguaje natural")
    parser.add_argument("--demo", action="store_true",
                        help="Sin API key: responde las preguntas del set de evaluación")
    parser.add_argument("--db", type=Path,
                        default=Path(os.getenv("TEXT2SQL_DB", RAIZ / "datos" / "minimarkets.duckdb")))
    parser.add_argument("--modelo", help="Modelo a usar (por defecto LLM_MODELO)")
    parser.add_argument("--detalle", action="store_true", help="Muestra cada paso del agente")
    args = parser.parse_args()

    try:
        agente = crear_agente(args.demo, args.db, args.modelo)
    except (RuntimeError, FileNotFoundError) as e:
        consola.print(f"[red]{e}[/]")
        raise SystemExit(1)
    consola.print(f"[dim]Modelo: {agente.modelo.nombre} · Base: {args.db.name}[/]")

    if args.pregunta:
        mostrar(agente.preguntar(args.pregunta), args.detalle)
        return

    consola.print("Escribe tu pregunta (o 'salir').")
    while True:
        try:
            pregunta = consola.input("[bold]> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if pregunta.lower() in {"salir", "exit", "q"}:
            break
        if pregunta:
            with consola.status("Pensando..."):
                res = agente.preguntar(pregunta)
            mostrar(res, args.detalle)


if __name__ == "__main__":
    main()
