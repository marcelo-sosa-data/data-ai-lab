"""
Uso:
    python -m kpis generar [--escala 0.2]                     # datos sintéticos
    python -m kpis catalogo                                   # métricas definidas en el YAML
    python -m kpis validar                                    # esquema, métricas y conciliación
    python -m kpis consultar tpv tasa_aprobacion --por rubro --grano mes --desde 2026-01-01
    python -m kpis consultar tasa_aprobacion --por emisor --donde region=Lima --sql --dialecto bigquery
    python -m kpis monitor                                    # alertas diarias y su explicación
    python -m kpis explicar tasa_aprobacion --fecha 2026-08-14
    python -m kpis explicar ticket_promedio --periodo 2026-08 --contra 2026-04
    python -m kpis todo                                       # generar, validar y monitor
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from . import formato as fmt
from .calendario import etiqueta_dia, etiqueta_periodo
from .capa import CapaSemantica, conectar
from .compilador import DIALECTOS, GRANOS, Consulta
from .explicacion import UMBRAL, Explicacion, explicar_dia, explicar_periodos
from .modelo import ErrorSemantico
from .monitor import eventos, evaluar, vigilar
from .resultados import guardar
from .rutas import RAIZ, ruta_db, ruta_resultados
from .validacion import huerfanos, no_aditividad, validar

consola = Console()
CIAN = "#22D3EE"
VERDE, ROJO, AMBAR = "#34D399", "#F87171", "#FBBF24"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}",
                 header_style="dim", box=None, padding=(0, 2))


def _filtros(donde: list[str] | None) -> dict[str, list[str]]:
    salida = {}
    for f in donde or []:
        if "=" not in f:
            raise ErrorSemantico(f"filtro inválido: {f}. Usa dimension=valor1,valor2")
        dim, valores = f.split("=", 1)
        salida[dim.strip()] = [v.strip() for v in valores.split(",")]
    return salida


def _mes(texto: str) -> tuple[str, str]:
    inicio = pd.Timestamp(texto + "-01" if len(texto) == 7 else texto)
    return str(inicio.date()), str((inicio + pd.offsets.MonthEnd(0)).date())


# ---------------------------------------------------------------- comandos

def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    with consola.status("Generando datos..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    con = conectar(ruta)
    n, f0, f1 = con.execute("SELECT COUNT(*), MIN(fecha), MAX(fecha) FROM transacciones").fetchone()
    nc, = con.execute("SELECT COUNT(*) FROM comercios").fetchone()
    con.close()
    consola.print(f"[bold]{ruta.name}[/] · {n:,} transacciones · {nc:,} comercios · "
                  f"{etiqueta_dia(f0, True)} a {etiqueta_dia(f1, True)}")
    return 0


def cmd_catalogo(args) -> int:
    d = CapaSemantica.desde_yaml().definicion
    t = _tabla("Métricas · semantica/tinkuy.yml")
    for c in ("Métrica", "Tipo", "Definición", "Responsable", "Monitor"):
        t.add_column(c)
    for n, m in d.metricas.items():
        defin = {"simple": m.medida, "ratio": f"{m.numerador} / {m.denominador}", "derivada": m.expr}[m.tipo]
        mon = f"{m.monitor.modelo}, umbral {m.monitor.umbral_minimo:g}" if m.monitor else ""
        t.add_row(f"[{CIAN}]{n}[/]", m.tipo, defin, m.responsable, mon)
    consola.print(t)
    consola.print(f"[dim]  Dimensiones: {', '.join(d.dimensiones())}[/]\n")
    return 0


def cmd_validar(args) -> int:
    capa = CapaSemantica.desde_yaml()
    con = conectar()
    with consola.status("Validando la capa contra la base..."):
        chequeos, conc = validar(capa, con)
        h = huerfanos(con)
        mes = con.execute("SELECT strftime(MAX(fecha), '%Y-%m-01') FROM transacciones").fetchone()[0]
        na = no_aditividad(capa, con, mes)
    con.close()
    t = _tabla("Validación de la capa semántica")
    for c in ("Grupo", "Chequeo", "", "Detalle"):
        t.add_column(c)
    for ch in chequeos:
        t.add_row(ch.grupo, ch.nombre, f"[{VERDE}]ok[/]" if ch.ok else f"[bold {ROJO}]falla[/]", ch.detalle)
    consola.print(t)
    consola.print(f"[dim]  Cobros sin comercio en el maestro: {h['transacciones']:,} de {h['comercios']} "
                  f"comercios (S/ {h['tpv']:,.0f} de TPV). Quedan como '(sin dato)', no se pierden.[/]")
    for m, x in na.items():
        consola.print(f"[dim]  {m} no es aditiva: en {etiqueta_periodo(mes, 'mes')} la suma diaria da "
                      f"{x['suma_diaria']:,} y el mes, {x['mes']:,}.[/]")
    consola.print()
    return 0 if all(c.ok for c in chequeos) else 1


def cmd_consultar(args) -> int:
    capa = CapaSemantica.desde_yaml()
    q = Consulta(metricas=args.metricas, dimensiones=args.por or [], grano=args.grano, desde=args.desde,
                 hasta=args.hasta, filtros=_filtros(args.donde))
    sql = capa.sql(q, args.dialecto)
    if args.sql or args.dialecto != "duckdb":
        consola.print(Syntax(sql, "sql", theme="monokai", background_color="default"))
        if args.dialecto != "duckdb":
            return 0
    con = conectar()
    df = capa.consultar(con, q)
    con.close()
    d = capa.definicion
    t = _tabla(" · ".join(d.metricas[m].etiqueta for m in args.metricas))
    claves = (["periodo"] if args.grano else []) + q.dimensiones
    for c in claves:
        t.add_column(c)
    for m in args.metricas:
        t.add_column(d.metricas[m].etiqueta, justify="right")
    for r in df.head(args.limite).itertuples(index=False):
        fila = r._asdict()
        celdas = [etiqueta_periodo(fila["periodo"], args.grano) if c == "periodo" else str(fila[c]) for c in claves]
        celdas += [fmt.valor(fila[m], d.metricas[m].formato) for m in args.metricas]
        t.add_row(*celdas)
    consola.print(t)
    if len(df) > args.limite:
        consola.print(f"[dim]  ... {len(df) - args.limite} filas más[/]")
    return 0


def mostrar_explicacion(e: Explicacion, capa: CapaSemantica, titulo: str, n: int = 5) -> None:
    m = capa.definicion.metricas[e.metrica]
    consola.print(f"\n[bold {CIAN}]{titulo}[/]")
    consola.print(f"  {m.etiqueta}: {fmt.valor(e.valor_base, m.formato)} ({e.descripcion_base}) -> "
                  f"[bold]{fmt.valor(e.valor_actual, m.formato)}[/]  "
                  f"[{ROJO if e.cambio < 0 else VERDE}]{fmt.cambio(e.valor_base, e.valor_actual, m.formato)}[/]\n")
    t = _tabla("Dónde está el cambio")
    for c in ("Dimensión", "Concentración", "Segmento", "Aporta", "Del cambio", "Peso", "Mezcla", "Tasa"):
        t.add_column(c, justify="left" if c in ("Dimensión", "Segmento") else "right")
    for r in e.ranking.head(n).itertuples():
        estilo = f"bold {CIAN}" if r.concentracion >= UMBRAL else ""
        t.add_row(f"[{estilo}]{r.dimension}[/]" if estilo else r.dimension, f"{r.concentracion:.2f}", r.segmento,
                  fmt.contribucion(r.contribucion, m.formato), f"{r.parte_del_cambio:.0%}",
                  f"{r.peso_segmento:.0%}", fmt.contribucion(r.efecto_mezcla, m.formato),
                  fmt.contribucion(r.efecto_tasa, m.formato))
    consola.print(t)
    top = e.ranking.iloc[0]
    if top.concentracion < UMBRAL:
        consola.print("[dim]  Ninguna dimensión concentra el cambio: se mueve parejo en todos los segmentos.[/]\n")
    else:
        seg = e.detalle[top.dimension].index[0] if top.n_segmentos > 1 else top.segmento
        consola.print(f"[dim]  Para bajar un nivel: --donde \"{top.dimension}={seg}\" --por <otra dimensión>[/]\n")


def cmd_explicar(args) -> int:
    capa = CapaSemantica.desde_yaml()
    con = conectar()
    filtros = _filtros(args.donde)
    if args.fecha:
        e = explicar_dia(capa, con, args.metrica, args.fecha, args.por, filtros)
        titulo = f"{args.metrica} · {etiqueta_dia(args.fecha, True)}"
    else:
        if not (args.periodo and args.contra):
            raise ErrorSemantico("usa --fecha, o --periodo junto con --contra")
        e = explicar_periodos(capa, con, args.metrica, _mes(args.periodo), _mes(args.contra), args.por, filtros)
        titulo = f"{args.metrica} · {etiqueta_periodo(_mes(args.periodo)[0], 'mes')} contra " \
                 f"{etiqueta_periodo(_mes(args.contra)[0], 'mes')}"
    con.close()
    if filtros:
        titulo += " · " + ", ".join(f"{k}={'/'.join(v)}" for k, v in filtros.items())
    mostrar_explicacion(e, capa, titulo)
    return 0


def cmd_monitor(args) -> int:
    capa = CapaSemantica.desde_yaml()
    con = conectar()
    inicio = time.time()
    with consola.status("Ajustando la línea base de cada día..."):
        serie = vigilar(capa, con)
        ev = eventos(serie)
        incidentes = con.execute("SELECT * FROM incidentes").df()
        evaluacion, falsas = evaluar(serie, incidentes)
        expl = []
        for r in ev.itertuples():
            e = explicar_dia(capa, con, r.metrica, r.peor_dia)
            for orden, top in enumerate(e.ranking.head(2).itertuples(), 1):
                expl.append({"metrica": r.metrica, "fecha": r.peor_dia, "orden": orden,
                             "valor_base": e.valor_base, "valor_actual": e.valor_actual,
                             "dimension": top.dimension, "segmento": top.segmento,
                             "concentracion": top.concentracion, "parte_del_cambio": top.parte_del_cambio})
    con.close()
    expl = pd.DataFrame(expl)
    guardar(ruta_resultados(), {
        "serie": serie, "eventos": ev, "evaluacion": evaluacion, "falsas": falsas, "explicaciones": expl,
        "corrida": pd.DataFrame([{"fecha": pd.Timestamp.now().floor("s"), "segundos": time.time() - inicio,
                                  "dias": serie.fecha.nunique()}])})

    d = capa.definicion
    t = _tabla(f"Alertas · {etiqueta_dia(serie.fecha.min(), True)} a {etiqueta_dia(serie.fecha.max(), True)}")
    for c in ("Métrica", "Días", "Peor día", "Valor", "Esperado", "z", "Dónde está el cambio"):
        t.add_column(c, justify="right" if c in ("Días", "Valor", "Esperado", "z") else "left")
    for r in ev.itertuples():
        s = serie[(serie.metrica == r.metrica) & (serie.fecha == r.peor_dia)].iloc[0]
        f = d.metricas[r.metrica].formato
        x = expl[(expl.metrica == r.metrica) & (expl.fecha == r.peor_dia) & (expl.concentracion >= UMBRAL)]
        donde = " · ".join(f"[{CIAN}]{y.dimension} = {y.segmento}[/]" for y in x.itertuples()) or "[dim]repartido[/]"
        t.add_row(r.metrica, str(r.dias), etiqueta_dia(r.peor_dia, True), fmt.valor(s.valor, f),
                  fmt.valor(s.esperado, f), f"{r.z_peor:+.1f}", donde)
    consola.print(t)
    detectados = int(evaluacion.detectado.sum())
    consola.print(f"[dim]  Incidentes reales detectados: {detectados} de {len(evaluacion)}. "
                  f"Días-alerta sin incidente: {len(falsas)} de {len(serie)} días-métrica evaluados.[/]\n")
    return 0


def cmd_todo(args) -> int:
    for f in (cmd_generar, cmd_validar, cmd_monitor):
        if f(args):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kpis", description="Capa semántica y monitor de KPIs de Tinkuy Pay.")
    sub = parser.add_subparsers(dest="comando", required=True)

    def _gen(p):
        p.add_argument("--escala", type=float, default=1.0)
        p.add_argument("--seed", type=int, default=42)

    _gen(sub.add_parser("generar", help="Genera los datos sintéticos"))
    sub.add_parser("catalogo", help="Lista las métricas del YAML")
    sub.add_parser("validar", help="Valida la capa contra la base")
    p = sub.add_parser("consultar", help="Consulta métricas por dimensiones")
    p.add_argument("metricas", nargs="+")
    p.add_argument("--por", nargs="*")
    p.add_argument("--grano", choices=list(GRANOS))
    p.add_argument("--desde")
    p.add_argument("--hasta")
    p.add_argument("--donde", action="append", help="dimension=valor1,valor2 (se puede repetir)")
    p.add_argument("--sql", action="store_true", help="muestra el SQL compilado")
    p.add_argument("--dialecto", choices=DIALECTOS, default="duckdb")
    p.add_argument("--limite", type=int, default=40)
    sub.add_parser("monitor", help="Corre el monitor diario y explica cada alerta")
    p = sub.add_parser("explicar", help="Descompone el cambio de una métrica por dimensión")
    p.add_argument("metrica")
    p.add_argument("--fecha")
    p.add_argument("--periodo", help="mes a explicar (AAAA-MM)")
    p.add_argument("--contra", help="mes base (AAAA-MM)")
    p.add_argument("--por", nargs="*")
    p.add_argument("--donde", action="append")
    _gen(sub.add_parser("todo", help="Genera, valida y corre el monitor"))

    args = parser.parse_args(argv)
    comandos = {"generar": cmd_generar, "catalogo": cmd_catalogo, "validar": cmd_validar,
                "consultar": cmd_consultar, "monitor": cmd_monitor, "explicar": cmd_explicar, "todo": cmd_todo}
    try:
        return comandos[args.comando](args)
    except (FileNotFoundError, ErrorSemantico) as e:
        consola.print(f"[red]{e.args[0] if e.args else e}[/]")
        return 1
