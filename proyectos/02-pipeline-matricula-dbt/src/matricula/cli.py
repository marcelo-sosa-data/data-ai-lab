"""
Uso:
    python -m matricula generar [--escala 0.1]   # exports crudos sintéticos
    python -m matricula build [--full-refresh]   # dbt build + registro de la corrida
    python -m matricula calidad                  # qué se limpió y si cuadra con lo inyectado
    python -m matricula resumen [--periodo 2026-2]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .consultas import Consultas, Kpis
from .pipeline import ResultadoBuild, correr_dbt
from .rutas import RAIZ, leer_manifiesto, ruta_db, ruta_raw

consola = Console()
CIAN = "#22D3EE"


def _pct(x: float | None, signo: bool = False) -> str:
    if x is None:
        return "-"
    return f"{x:+.1%}" if signo else f"{x:.1%}"


def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    raw = ruta_raw()
    with consola.status("Generando exports..."):
        generar(raw, escala=args.escala, seed=args.seed, corte=args.corte)
    meta = leer_manifiesto(raw)
    db = ruta_db()
    if db.exists():
        # el modelo incremental tiene datos del export anterior: hay que reconstruir
        db.unlink()
        consola.print(f"[dim]Se borró {db.name}: el próximo build reconstruye todo desde cero.[/]")
    consola.print(f"Exports en [bold]{raw}[/] · corte {meta['corte']} · periodos {meta['periodos'][0]} a "
                  f"{meta['periodos'][-1]}")
    return 0


def mostrar_build(res: ResultadoBuild) -> None:
    t = Table(title=f"dbt {res.comando}", title_justify="left", title_style=f"bold {CIAN}",
              header_style="dim", box=None, padding=(0, 2))
    t.add_column("Tipo")
    t.add_column("OK", justify="right", style="green")
    t.add_column("Aviso", justify="right", style="yellow")
    t.add_column("Falla", justify="right", style="red")
    for tipo, ok in [("seed", "success"), ("modelo", "success"), ("test", "pass"), ("test unitario", "pass")]:
        t.add_row(tipo, str(res.contar(tipo, ok)), str(res.contar(tipo, "warn")),
                  str(res.contar(tipo, "fail", "error")))
    consola.print(t)
    for n in res.avisos:
        consola.print(f"  [yellow]aviso[/]  {n.nombre}: {n.filas} filas")
    for n in res.fallas:
        consola.print(f"  [red]falla[/]  {n.nombre}: {n.mensaje}")
    if res.error:
        consola.print(f"[red]{res.error}[/]")
    estado = "[green]OK[/]" if res.exito else "[red]CON FALLAS[/]"
    consola.print(f"\n{estado} · {len(res.nodos)} nodos en {res.segundos:.1f} s · base: {ruta_db().name}")


def cmd_build(args) -> int:
    with consola.status("Corriendo dbt build..."):
        res = correr_dbt("build", full_refresh=args.full_refresh)
    mostrar_build(res)
    return 0 if res.exito else 1


def cmd_calidad(args) -> int:
    esperado = leer_manifiesto()["anomalias"]
    c = Consultas()
    df = c.calidad()
    c.cerrar()
    t = Table(title="Calidad de datos del export", title_justify="left", title_style=f"bold {CIAN}",
              header_style="dim", box=None, padding=(0, 1))
    t.add_column("Regla", min_width=36)
    for col, j in [("Tabla", "left"), ("Acción", "left"), ("Registros", "right"),
                   ("% tabla", "right"), ("Inyectados", "right"), ("", "left")]:
        t.add_column(col, justify=j, no_wrap=True)
    todo_ok = True
    for f in df.itertuples():
        inj = esperado.get(f.regla_id)
        ok = inj == f.registros
        todo_ok &= ok
        t.add_row(f.regla, f.tabla, f.accion, f"{f.registros:,}", _pct(f.pct),
                  "-" if inj is None else f"{inj:,}", "[green]cuadra[/]" if ok else "[red]no cuadra[/]")
    consola.print(t)
    return 0 if todo_ok else 1


def cmd_resumen(args) -> int:
    c = Consultas()
    periodo = args.periodo or c.periodos()[-1]
    k = c.kpis(periodo)
    deuda = c.dia_matricula_por_deuda()
    c.cerrar()
    t = Table(title=f"Matrícula {periodo}", title_justify="left", title_style=f"bold {CIAN}",
              header_style="dim", box=None, padding=(0, 2))
    t.add_column("Indicador")
    t.add_column("Valor", justify="right", style=CIAN)
    t.add_column("vs año anterior", justify="right")
    t.add_row("Alumnos matriculados", f"{k.matriculados:,}",
              _pct(Kpis.variacion(k.matriculados, k.matriculados_anio_anterior), True))
    t.add_row("Ingresantes", f"{k.ingresantes:,}", _pct(Kpis.variacion(k.ingresantes, k.ingresantes_anio_anterior), True))
    t.add_row("Matrícula extemporánea", _pct(k.pct_extemporanea), "")
    t.add_row("Alumnos con cuotas vencidas", _pct(k.pct_con_deuda), "")
    t.add_row("Secciones presenciales con baja demanda", f"{k.secciones_baja_demanda} de {k.secciones}", "")
    consola.print(t)
    consola.print()
    for f in deuda.itertuples():
        consola.print(f"  {f.grupo:<30} se matricula en promedio el día [bold]{f.dia_promedio:.1f}[/]"
                      f" · extemporánea {_pct(f.pct_extemporanea)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="matricula", description="Pipeline de matrícula con dbt + DuckDB")
    sub = ap.add_subparsers(dest="comando", required=True)

    g = sub.add_parser("generar", help="genera los exports crudos sintéticos")
    g.add_argument("--escala", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--corte", type=date.fromisoformat, default=date(2026, 10, 24))
    g.set_defaults(func=cmd_generar)

    b = sub.add_parser("build", help="dbt build (seeds, modelos y tests)")
    b.add_argument("--full-refresh", action="store_true", help="reconstruye también el modelo incremental")
    b.set_defaults(func=cmd_build)

    sub.add_parser("calidad", help="reglas de calidad vs anomalías inyectadas").set_defaults(func=cmd_calidad)

    r = sub.add_parser("resumen", help="indicadores del periodo")
    r.add_argument("--periodo")
    r.set_defaults(func=cmd_resumen)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        consola.print(f"[red]{e}[/]")
        return 2


if __name__ == "__main__":
    sys.exit(main())
