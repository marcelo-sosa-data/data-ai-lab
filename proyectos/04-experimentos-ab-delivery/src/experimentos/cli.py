"""
Uso:
    python -m experimentos generar [--escala 0.2]      # datos sintéticos
    python -m experimentos analizar [--exp EXP-02]     # lee los experimentos y decide
    python -m experimentos aa [--repeticiones 2000]    # falsos positivos al mirar cada día
    python -m experimentos planificar                  # MDE por semanas de duración
    python -m experimentos reporte EXP-02              # readout en Markdown
    python -m experimentos todo                        # todo lo anterior
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
from rich.console import Console
from rich.table import Table

from .aa import estudio_aa
from .analisis import leer
from .calendario import rango
from .catalogo import EXPERIMENTOS, METRICAS, por_id
from .metricas import conectar
from .planificacion import tabla_planificacion
from .reporte import readout
from .resultados import guardar, tablas_de_lecturas
from .rutas import RAIZ, ruta_db, ruta_reportes, ruta_resultados

consola = Console()
CIAN = "#22D3EE"
COLOR_VEREDICTO = {"lanzar": "bold #34D399", "no lanzar": "bold #F87171", "extender": "bold #FBBF24",
                   "invalidar": "bold #A78BFA"}


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}",
                 header_style="dim", box=None, padding=(0, 2))


def _ic(r) -> str:
    return f"{r.relativo_bajo:+.1%} a {r.relativo_alto:+.1%}"


def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    with consola.status("Generando datos..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    con = conectar(ruta)
    n_u, = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()
    n_p, f0, f1 = con.execute("SELECT COUNT(*), MIN(fecha), MAX(fecha) FROM pedidos").fetchone()
    n_e, = con.execute("SELECT COUNT(*) FROM exposiciones WHERE id_experimento <> 'AA'").fetchone()
    con.close()
    consola.print(f"[bold]{ruta.name}[/] · {n_u:,} usuarios · {n_p:,} pedidos · {n_e:,} exposiciones · "
                  f"{f0:%d/%m/%Y} a {f1:%d/%m/%Y}")
    return 0


def cmd_analizar(args) -> int:
    con = conectar(ruta_db())
    exps = [por_id(args.exp)] if args.exp else EXPERIMENTOS
    inicio = time.time()
    with consola.status("Leyendo experimentos..."):
        lecturas = [leer(con, e) for e in exps]
    con.close()
    if not args.exp:
        guardar(ruta_resultados(), tablas_de_lecturas(lecturas) | {"corrida": pd.DataFrame([{
            "fecha": pd.Timestamp.now().floor("s"), "experimentos": len(lecturas),
            "segundos": time.time() - inicio}])})
    mostrar_resumen(lecturas)
    if args.exp:
        mostrar_detalle(lecturas[0])
    return 0


def mostrar_resumen(lecturas) -> None:
    t = _tabla("Experimentos 2026 · Chasqui")
    for c in ("Exp.", "Nombre", "Expuestos", "SRM p", "Primaria", "Efecto", "IC 95%", "Veredicto"):
        t.add_column(c, justify="right" if c in ("Expuestos", "SRM p", "Efecto") else "left")
    for lec in lecturas:
        e, p = lec.experimento, lec.lecturas[lec.experimento.primaria]
        srm_txt = f"{lec.p_srm:.2g}"
        if lec.p_srm < 0.001:
            srm_txt = f"[bold #A78BFA]{srm_txt}[/]"
        efecto = f"[{CIAN}]{p.relativo:+.1%}[/]" if p.significativo else f"{p.relativo:+.1%}"
        v = lec.decision.veredicto
        t.add_row(e.id, e.nombre, f"{lec.n_control + lec.n_tratamiento:,}", srm_txt,
                  METRICAS[e.primaria]["nombre"], efecto, _ic(p), f"[{COLOR_VEREDICTO[v]}]{v}[/]")
    consola.print(t)
    consola.print("[dim]  Efecto relativo con CUPED (método delta en ratios). En cian: p < 0.05.[/]\n")


def mostrar_detalle(lec) -> None:
    e = lec.experimento
    t = _tabla(f"{e.id} · {e.nombre} · {rango(e.inicio, e.fin)}")
    for c in ("Métrica", "Rol", "Método", "Control", "Tratamiento", "Efecto", "IC 95%", "p"):
        t.add_column(c, justify="left" if c in ("Métrica", "Rol", "Método") else "right")
    for r in lec.metricas.itertuples():
        f = METRICAS[r.metrica]["formato"]
        t.add_row(r.nombre, r.rol, r.metodo, format(r.media_control, f), format(r.media_tratamiento, f),
                  f"[{CIAN}]{r.relativo:+.1%}[/]" if r.p_valor < 0.05 else f"{r.relativo:+.1%}", _ic(r),
                  f"{r.p_valor:.3f}")
    consola.print(t)
    v = lec.decision.veredicto
    consola.print(f"\n  [{COLOR_VEREDICTO[v]}]{v.upper()}[/] · {lec.decision.motivo}\n")


def cmd_aa(args) -> int:
    con = conectar(ruta_db())
    with consola.status(f"A/A: {args.repeticiones:,} repartos al azar, leídos cada día..."):
        curva, res = estudio_aa(con, args.repeticiones)
    con.close()
    guardar(ruta_resultados(), {"aa_curva": curva, "aa_resumen": pd.DataFrame([res])})
    t = _tabla(f"A/A · {res['usuarios']:,} usuarios · {rango(res['inicio'], res['fin'])} · "
               f"{res['repeticiones']:,} repartos")
    for c in ("Mirando hasta el día", "p < 0.05 algún día", "Una sola mirada", "mSPRT algún día"):
        t.add_column(c, justify="right")
    for r in curva[curva.dia.isin([1, 7, 14, 21, 28])].itertuples():
        t.add_row(str(r.dia), f"[bold #F87171]{r.mirando_cada_dia:.1%}[/]", f"{r.una_mirada:.1%}",
                  f"[{CIAN}]{r.msprt_cada_dia:.1%}[/]")
    consola.print(t)
    consola.print("[dim]  Proporción de repartos sin efecto real que se habrían declarado ganadores. "
                  "Nominal: 5%.[/]\n")
    return 0


def cmd_planificar(args) -> int:
    con = conectar(ruta_db())
    with consola.status("Estimando varianza y tráfico..."):
        plan = tabla_planificacion(con)
    con.close()
    guardar(ruta_resultados(), {"planificacion": plan})
    t = _tabla("Efecto mínimo detectable (80% de potencia, α = 5%, 50/50)")
    for c in ("Métrica", "Semanas", "Usuarios", "ρ con el pre", "MDE sin CUPED", "MDE con CUPED"):
        t.add_column(c, justify="left" if c == "Métrica" else "right")
    for r in plan.itertuples():
        t.add_row(METRICAS[r.metrica]["nombre"], str(r.semanas), f"{r.usuarios:,}", f"{r.rho:.2f}",
                  f"{r.mde_sin_cuped:.1%}", f"[{CIAN}]{r.mde_con_cuped:.1%}[/]")
    consola.print(t)
    return 0


def cmd_reporte(args) -> int:
    con = conectar(ruta_db())
    lec = leer(con, por_id(args.exp))
    con.close()
    carpeta = ruta_reportes()
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{lec.experimento.id}.md"
    ruta.write_text(readout(lec), encoding="utf-8")
    v = lec.decision.veredicto
    consola.print(f"[{COLOR_VEREDICTO[v]}]{v.upper()}[/] · {lec.decision.motivo}")
    consola.print(f"[dim]  {ruta}[/]")
    return 0


def cmd_todo(args) -> int:
    for f in (cmd_generar, cmd_analizar, cmd_aa, cmd_planificar):
        if f(args):
            return 1
    for e in EXPERIMENTOS:
        args.exp = e.id
        cmd_reporte(args)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experimentos", description="Lectura de experimentos A/B.")
    sub = parser.add_subparsers(dest="comando", required=True)

    def _gen(p):
        p.add_argument("--escala", type=float, default=1.0)
        p.add_argument("--seed", type=int, default=42)

    _gen(sub.add_parser("generar", help="Genera los datos sintéticos"))
    p = sub.add_parser("analizar", help="Lee los experimentos y aplica la regla de decisión")
    p.add_argument("--exp", default=None)
    p = sub.add_parser("aa", help="Estudio A/A de falsos positivos")
    p.add_argument("--repeticiones", type=int, default=2000)
    sub.add_parser("planificar", help="MDE según la duración")
    p = sub.add_parser("reporte", help="Readout en Markdown de un experimento")
    p.add_argument("exp")
    p = sub.add_parser("todo", help="Genera, analiza, A/A, planificación y reportes")
    _gen(p)
    p.add_argument("--repeticiones", type=int, default=2000)
    p.set_defaults(exp=None)

    args = parser.parse_args(argv)
    comandos = {"generar": cmd_generar, "analizar": cmd_analizar, "aa": cmd_aa, "planificar": cmd_planificar,
                "reporte": cmd_reporte, "todo": cmd_todo}
    try:
        return comandos[args.comando](args)
    except (FileNotFoundError, KeyError) as e:
        consola.print(f"[red]{e.args[0] if e.args else e}[/]")
        return 1
