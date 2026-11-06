"""
Uso:
    python -m desercion generar [--escala 0.15]    # datos sintéticos
    python -m desercion entrenar [--rondas 600]    # evaluación temporal + modelo vigente
    python -m desercion supervivencia              # Kaplan-Meier, riesgo por semana y Cox
    python -m desercion lista [--sede "Lima Norte"] [--n 15]
    python -m desercion todo                       # generar, entrenar y supervivencia
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
from rich.console import Console
from rich.table import Table

from . import supervivencia as sv
from .datos import cargar, desenlaces
from .entrenamiento import CAPACIDAD, evaluar, vigente
from .features import estaticas, panel
from .resultados import guardar, leer, tablas
from .rutas import RAIZ, ruta_db, ruta_resultados

consola = Console()
CIAN = "#22D3EE"
POLITICAS = {"modelo": "LightGBM", "logistica": "Regresión logística",
             "regla_ordenada": "Regla + orden por alertas", "regla_actual": "Regla actual (sin orden)"}


def _pct(x, dec=0) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:.{dec}%}"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}", header_style="dim",
                 box=None, padding=(0, 2))


def _base(con_causas=False):
    try:
        return cargar(ruta_db(), con_causas=con_causas)
    except FileNotFoundError as e:
        consola.print(f"[red]{e}[/]")
        return None


def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    with consola.status("Generando datos..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    b = cargar(ruta)
    d = desenlaces(b)
    tasa = d[d.deserta.notna() & ~d.egresa].deserta.mean()
    consola.print(f"[bold]{ruta.name}[/] · {len(b.alumnos):,} alumnos · {len(b.matriculas):,} matrículas · "
                  f"{len(b.asistencia):,} semanas de asistencia · {b.periodos.periodo.min()} a {b.periodo_actual} "
                  f"(semana {b.semana_actual}) · deserción [{CIAN}]{tasa:.1%}[/] por semestre")
    return 0


def cmd_entrenar(args) -> int:
    b = _base(con_causas=True)
    if b is None:
        return 1
    inicio = time.time()
    with consola.status("Armando el panel alumno-semana..."):
        pnl = panel(b)
    with consola.status("Evaluación: entrenando LightGBM y logística..."):
        res = evaluar(b, pnl, rondas=args.rondas)
    with consola.status("Modelo vigente y lista de la semana..."):
        vig = vigente(b, pnl, rondas=args.rondas)
    seg = time.time() - inicio
    ruta = ruta_resultados()
    guardar(ruta, {**res, **vig, "corrida": pd.DataFrame([{"fecha": pd.Timestamp.now().floor("s"),
                                                            "segundos": seg, "filas_panel": len(pnl)}])})
    mostrar_evaluacion(res, seg)
    return 0


def mostrar_evaluacion(res: dict, seg: float) -> None:
    p = res["particion"].iloc[0]
    m = res["metricas_semana"].pivot(index="semana", columns="modelo", values="auc_pr")
    tasa = res["metricas_semana"].groupby("semana").tasa.first()
    consola.print(f"[bold {CIAN}]Prueba {p.prueba}[/] [dim]· entrenado con {p.entrenamiento.split(', ')[0]} a "
                  f"{p.entrenamiento.split(', ')[-1]} · calibrado con {p.calibracion}[/]")
    t = _tabla("AUC-PR por semana del ciclo")
    for c in ("Semana", "Deserción", "AUC-PR LightGBM", "AUC-PR logística"):
        t.add_column(c, justify="right")
    for w in (2, 4, 6, 8, 10, 12, 14, 16):
        if w in m.index:
            t.add_row(str(w), _pct(tasa[w], 1), f"[{CIAN}]{m.loc[w, 'LightGBM']:.3f}[/]", f"{m.loc[w, 'Logística']:.3f}")
    consola.print(t)
    e = res["ece"].set_index("modelo").ece
    consola.print(f"[dim]  Error de calibración (ECE): {e['LightGBM sin calibrar']:.3f} sin calibrar → "
                  f"{e['LightGBM calibrado']:.3f} calibrado[/]\n")

    c = res["capacidad"]
    c = c[c.capacidad == p.capacidad].set_index("politica")
    t = _tabla(f"Lista de contacto · {p.capacidad} llamadas por semana · {p.desertores_prueba:,} desertores")
    for col in ("Política", "Contactados", "Precisión", "Desertores alcanzados", "Anticipación (mediana)"):
        t.add_column(col, justify="left" if col == "Política" else "right")
    for pol, nombre in POLITICAS.items():
        r = c.loc[pol]
        estilo = f"bold {CIAN}" if pol == "modelo" else ""
        t.add_row(nombre, f"{r.contactos:,.0f}", _pct(r.precision, 1),
                  f"[{estilo}]{_pct(r.alcanzados_pct, 1)}[/]" if estilo else _pct(r.alcanzados_pct, 1),
                  f"{r.anticipacion_mediana:.0f} semanas")
    consola.print(t)
    consola.print(f"\n  {res['importancia'].variable.iloc[0]} es la variable que más pesa · {seg:.0f} s\n")


def cmd_supervivencia(args) -> int:
    b = _base()
    if b is None:
        return 1
    with consola.status("Kaplan-Meier, riesgo semanal y Cox..."):
        t = sv.tabla(estaticas(b), desenlaces(b))
        curvas, pruebas = [], []
        for g in sv.GRUPOS:
            km, p = sv.kaplan_meier(t, g)
            curvas.append(km)
            pruebas.append({"grupo": g, "p_logrank": p})
        haz = sv.riesgo_semanal(t)
        cox = sv.cox_landmark(panel(b, semanas=[4]), semana=4)
    guardar(ruta_resultados(), {"km": pd.concat(curvas, ignore_index=True), "logrank": pd.DataFrame(pruebas),
                                "riesgo_semanal": haz, "cox": cox,
                                "cox_resumen": pd.DataFrame([{"concordancia": cox.attrs["concordancia"],
                                                              "alumnos": cox.attrs["alumnos"]}])})
    mostrar_supervivencia(haz, cox)
    return 0


def mostrar_supervivencia(haz: pd.DataFrame, cox: pd.DataFrame) -> None:
    entre = haz[haz.semana == 17].iloc[0]
    total = haz.abandonos.sum()
    pico = haz[haz.semana <= 16].sort_values("riesgo").iloc[-1]
    consola.print(f"  {total:,} deserciones · [{CIAN}]{entre.abandonos / total:.0%}[/] entre semestres · "
                  f"pico dentro del ciclo en la semana {pico.semana:.0f} ({pico.riesgo:.2%} de los que seguían)\n")
    consola.print(f"[bold {CIAN}]Cox landmark en la semana 4[/] [dim]· {cox.attrs['alumnos']:,} alumno-semestres · "
                  f"concordancia {cox.attrs['concordancia']:.3f}[/]")
    t = _tabla("Hazard ratios")
    for col in ("Variable", "HR", "IC 95%", "Prevalencia"):
        t.add_column(col, justify="left" if col == "Variable" else "right")
    for r in cox.itertuples():
        t.add_row(r.descripcion, f"[{CIAN}]{r.hr:.2f}[/]" if r.hr > 1 else f"{r.hr:.2f}",
                  f"{r.ic_inf:.2f} - {r.ic_sup:.2f}", _pct(r.prevalencia))
    consola.print(t)
    consola.print()


def cmd_lista(args) -> int:
    ruta = ruta_resultados()
    if "lista" not in tablas(ruta):
        consola.print("[red]No hay lista. Corre primero: python -m desercion entrenar[/]")
        return 1
    lista = leer(ruta, "lista")
    vig = leer(ruta, "vigente").iloc[0]
    if args.sede:
        lista = lista[lista.sede == args.sede]
    t = _tabla(f"Lista de contacto · {vig.periodo} semana {vig.semana}"
               + (f" · {args.sede}" if args.sede else "") + f" · primeros {args.n} de {len(lista):,} activos")
    for col in ("#", "Código", "Sede", "Ciclo", "Riesgo", "vs sem. ant.", "Por qué"):
        t.add_column(col, justify="right" if col in ("#", "Ciclo", "Riesgo", "vs sem. ant.") else "left",
                     no_wrap=col != "Por qué")
    for r in lista.head(args.n).itertuples():
        delta = r.riesgo - r.riesgo_semana_anterior if pd.notna(r.riesgo_semana_anterior) else None
        t.add_row(str(r.puesto), r.codigo, r.sede, str(r.ciclo), f"[{CIAN}]{r.riesgo:.0%}[/]",
                  "nuevo" if delta is None else f"{delta * 100:+.0f} pts", r.razon_1 + " · " + r.razon_2)
    consola.print(t)
    a = leer(ruta, "ausentes")
    consola.print(f"\n  Además, {len(a):,} alumnos matriculados no asistieron en toda la semana {vig.semana}: "
                  f"van primero, sin pasar por el modelo.\n")
    return 0


def cmd_todo(args) -> int:
    for f in (cmd_generar, cmd_entrenar, cmd_supervivencia):
        if f(args):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="desercion", description="Alerta temprana de deserción universitaria")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--escala", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=42)
    e = sub.add_parser("entrenar")
    e.add_argument("--rondas", type=int, default=600)
    sub.add_parser("supervivencia")
    li = sub.add_parser("lista")
    li.add_argument("--sede")
    li.add_argument("--n", type=int, default=15)
    t = sub.add_parser("todo")
    t.add_argument("--escala", type=float, default=1.0)
    t.add_argument("--seed", type=int, default=42)
    t.add_argument("--rondas", type=int, default=600)
    args = ap.parse_args(argv)
    return {"generar": cmd_generar, "entrenar": cmd_entrenar, "supervivencia": cmd_supervivencia,
            "lista": cmd_lista, "todo": cmd_todo}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
