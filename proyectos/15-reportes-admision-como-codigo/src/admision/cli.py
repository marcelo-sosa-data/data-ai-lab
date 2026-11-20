"""
Uso:
    python -m admision generar [--escala 0.2]   # exports sintéticos de tres campañas
    python -m admision procesar                 # lee, modela, prueba y, si no hay errores, publica la base del sitio
    python -m admision probar                   # solo las pruebas de datos (sale con 1 si alguna bloquea)
    python -m admision comparar                 # reporte actual y nuevo contra la verdad del generador
    python -m admision incidencias              # 15 incidencias sembradas: qué publica cada proceso
    python -m admision todo                     # generar si falta, incidencias, comparar y procesar
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import catalogos as K
from .comparar import cifras, pendientes, proyeccion
from .incidencias import evaluar, resumen
from .lectura import leer_todo
from .modelo import construir
from .publicar import DESTINO, publicar
from .pruebas import correr, hay_bloqueo

RAIZ = Path(__file__).parents[2]
DATOS = Path(os.getenv("ADMISION_DATOS", RAIZ / "datos"))
CRUDO = DATOS / "crudo"
VERDAD = DATOS / "verdad"
INCIDENCIAS = DATOS / "incidencias.parquet"
COMPARACION = DATOS / "comparacion.parquet"
PENDIENTES = DATOS / "pendientes_comparados.parquet"
PROYECCION = DATOS / "proyeccion_revisada.parquet"

consola = Console()
CIAN = "#22D3EE"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}", header_style="dim",
                 box=None, padding=(0, 2))


def _pct(v) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:+.1%}"


def cmd_generar(a) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar
    t = time.time()
    generar(DATOS, escala=a.escala, seed=a.seed)
    consola.print(f"Exports en {CRUDO} ({time.time() - t:.1f} s)")
    return 0


def _modelar():
    lectura = leer_todo(CRUDO)
    con = construir(lectura, ruta=DATOS / "admision.duckdb")
    return con, correr(con)


def _mostrar_pruebas(resultados) -> None:
    t = _tabla("Pruebas de datos")
    for col in ("prueba", "severidad", "filas", "resultado"):
        t.add_column(col, justify="right" if col == "filas" else "left")
    for r in resultados:
        estado = "[green]aprobada[/]" if r.aprobada else ("[red]bloquea[/]" if r.bloquea else "[yellow]aviso[/]")
        t.add_row(r.nombre, r.severidad, str(r.filas), estado)
    consola.print(t)
    for r in resultados:
        if not r.aprobada:
            detalle = r.error_sql or (r.muestra[0] if r.muestra else "")
            consola.print(f"  [dim]{r.nombre}:[/] {escape(str(detalle))}")


def _extras() -> dict[str, pd.DataFrame]:
    """Resultados de la comparación e incidencias para el sitio (vacíos si no se corrieron)."""
    vacios = {
        "comparacion": ["campania", "medida", "as_is", "to_be", "verdad", "error_as_is", "error_to_be"],
        "pendientes_comparados": ["reporte", "en_lista", "ya_pagaron", "no_son_ingresantes_reales",
                                  "repetidos", "llamadas_inutiles", "pct_inutiles"],
        "proyeccion_revisada": ["sede", "vacantes", "matriculados_hoy", "proyectados", "al_cierre", "error",
                                "cobertura_proyectada", "cobertura_al_cierre"],
        "incidencias": ["incidencia", "descripcion", "actual_desvio", "actual_cifra", "actual_resultado",
                        "nuevo_resultado", "nuevo_desvio_si_publicara", "nuevo_cifra", "pruebas_con_error", "avisos"],
    }
    rutas = {"comparacion": COMPARACION, "pendientes_comparados": PENDIENTES, "incidencias": INCIDENCIAS,
             "proyeccion_revisada": PROYECCION}
    return {k: pd.read_parquet(rutas[k]) if rutas[k].exists() else pd.DataFrame(columns=cols)
            for k, cols in vacios.items()}


def cmd_procesar(a) -> int:
    t = time.time()
    con, resultados = _modelar()
    _mostrar_pruebas(resultados)
    if hay_bloqueo(resultados):
        consola.print("[red]Hay pruebas con error: no se publica. El sitio queda con la última versión buena.[/]")
        return 1
    destino = publicar(con, resultados, extras=_extras())
    kpi = con.sql(f"SELECT * FROM kpi_campania WHERE campania = '{K.CAMPANIA_ACTUAL}'").df().iloc[0]
    consola.print(f"Publicado en {destino} ({time.time() - t:.1f} s). {K.CAMPANIA_ACTUAL} al {str(kpi['corte'])[:10]}: "
                  f"{kpi['postulantes']:,} postulantes, {kpi['ingresantes']:,} ingresantes, "
                  f"{kpi['matriculados']:,} matriculados.")
    return 0


def cmd_probar(a) -> int:
    _, resultados = _modelar()
    _mostrar_pruebas(resultados)
    return 1 if hay_bloqueo(resultados) else 0


def cmd_comparar(a) -> int:
    con, _ = _modelar()
    df = cifras(con, CRUDO, VERDAD)
    pen = pendientes(con, CRUDO, VERDAD)
    df.to_parquet(COMPARACION, index=False)
    pen.to_parquet(PENDIENTES, index=False)
    proy = proyeccion(con, VERDAD)
    proy.to_parquet(PROYECCION, index=False)
    t = _tabla("Reporte actual (AS IS) y nuevo (TO BE) contra lo que pasó")
    for col in ("campaña", "medida", "AS IS", "TO BE", "verdad", "error AS IS", "error TO BE"):
        t.add_column(col, justify="left" if col in ("campaña", "medida") else "right")
    for r in df.itertuples():
        t.add_row(r.campania, r.medida, f"{r.as_is:,}", f"{r.to_be:,}",
                  "-" if pd.isna(r.verdad) else f"{int(r.verdad):,}", _pct(r.error_as_is), _pct(r.error_to_be))
    consola.print(t)
    t = _tabla(f"Lista de ingresantes por llamar, {K.CAMPANIA_ACTUAL}")
    for col in ("reporte", "en lista", "ya pagaron", "no son reales", "repetidos", "llamadas inútiles"):
        t.add_column(col, justify="left" if col == "reporte" else "right")
    for r in pen.itertuples():
        t.add_row(r.reporte, str(r.en_lista), str(r.ya_pagaron), str(r.no_son_ingresantes_reales),
                  str(r.repetidos), f"{r.llamadas_inutiles} ({r.pct_inutiles:.1%})")
    consola.print(t)
    if proy["al_cierre"].notna().all():
        t = _tabla(f"Proyección de matriculados por sede contra el cierre real de {K.CAMPANIA_ACTUAL}")
        for col in ("sede", "vacantes", "hoy", "proyectados", "al cierre", "error", "cobertura proy.", "cobertura real"):
            t.add_column(col, justify="left" if col == "sede" else "right")
        for r in proy.itertuples():
            t.add_row(r.sede, f"{r.vacantes:,.0f}", f"{r.matriculados_hoy:,.0f}", f"{r.proyectados:,.0f}",
                      f"{r.al_cierre:,.0f}", _pct(r.error), f"{r.cobertura_proyectada:.1%}", f"{r.cobertura_al_cierre:.1%}")
        consola.print(t)
    return 0


def cmd_incidencias(a) -> int:
    t0 = time.time()
    df = evaluar(CRUDO)
    df.to_parquet(INCIDENCIAS, index=False)
    t = _tabla("Incidencias sembradas en los exports de la campaña en curso")
    for col in ("incidencia", "reporte actual", "desvío", "proceso nuevo", "pruebas que fallan"):
        t.add_column(col, justify="right" if col == "desvío" else "left")
    for r in df.itertuples():
        color = {"bloquea": "green", "absorbe": "green", "publica distinto": "red"}[r.nuevo_resultado]
        t.add_row(r.incidencia, r.actual_resultado, f"{r.actual_desvio:.1%}" if r.actual_desvio else "-",
                  f"[{color}]{r.nuevo_resultado}[/]", r.pruebas_con_error or r.avisos)
    consola.print(t)
    s = resumen(df)
    consola.print(f"Reporte actual: publica cifras distintas en {s['actual_publica_distinto']} de {s['incidencias']} "
                  f"({s['actual_sutiles']} con un desvío menor a 20%). Proceso nuevo: bloquea {s['nuevo_bloquea']}, "
                  f"absorbe {s['nuevo_absorbe']} y publica distinto {s['nuevo_publica_distinto']}. "
                  f"({time.time() - t0:.0f} s)")
    return 0


def cmd_todo(a) -> int:
    if not (CRUDO / K.CAMPANIA_ACTUAL).exists():
        cmd_generar(a)
    cmd_incidencias(a)
    cmd_comparar(a)
    return cmd_procesar(a)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="admision", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--escala", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=15)
    for nombre in ("procesar", "probar", "comparar", "incidencias"):
        sub.add_parser(nombre)
    t = sub.add_parser("todo")
    t.add_argument("--escala", type=float, default=1.0)
    t.add_argument("--seed", type=int, default=15)
    a = ap.parse_args(argv)
    return {"generar": cmd_generar, "procesar": cmd_procesar, "probar": cmd_probar, "comparar": cmd_comparar,
            "incidencias": cmd_incidencias, "todo": cmd_todo}[a.cmd](a)


__all__ = ["main", "DESTINO"]
