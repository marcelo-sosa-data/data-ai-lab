"""
Uso:
    python -m elasticidad generar [--escala 0.3]   # base sintética de Qollqa
    python -m elasticidad ajustar                  # modelo hasta el corte y modelo con toda la historia
    python -m elasticidad evaluar                  # promociones de may-oct 2026: planilla, modelo y realidad
    python -m elasticidad simular --sku 501 --inicio 2026-11-16 --descuento 0.2 [--semanas 1] [--encarte] [--aporte 0.5]
    python -m elasticidad todo                     # generar, ajustar y evaluar
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

from . import evaluacion as E
from . import modelo as M
from .consultas import FORMATOS, conectar, matrices
from .resultados import guardar, leer, tablas
from .rutas import RAIZ, ruta_db, ruta_modelos, ruta_resultados
from .simulador import Escenario, Simulador

consola = Console()
CIAN = "#22D3EE"
CORTE = pd.Timestamp("2026-05-04")  # se ajusta con lo anterior y se evalúa lo que empieza desde aquí


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}", header_style="dim",
                 box=None, padding=(0, 2))


def _soles(x: float) -> str:
    return f"S/ {x:,.0f}"


def _con():
    try:
        return conectar(ruta_db())
    except FileNotFoundError as e:
        consola.print(f"[red]{e}[/]")
        return None


def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    inicio = time.time()
    with consola.status("Generando datos..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    con = conectar(ruta)
    n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("tiendas", "productos", "ventas_semana", "promociones")}
    con.close()
    consola.print(f"[bold]{ruta.name}[/] · {n['tiendas']} locales · {n['productos']} productos · "
                  f"{n['ventas_semana']:,} filas de venta semanal · {n['promociones']} promociones · "
                  f"{time.time() - inicio:.0f} s")
    return 0


def cmd_ajustar(args) -> int:
    con = _con()
    if con is None:
        return 1
    m = matrices(con)
    n_corte = int((m.semanas < CORTE).sum())
    salida = {}
    for nombre, mm in (("corte", m.recortar(n_corte)), ("final", m)):
        inicio = time.time()
        with consola.status(f"Muestreando la posterior ({nombre}, {len(mm.semanas)} semanas)..."):
            post, meta, diag = M.ajustar(mm, draws=args.draws, tune=args.tune)
        M.guardar(ruta_modelos(), nombre, post, meta, diag)
        diag["segundos"] = round(time.time() - inicio, 1)
        salida[nombre] = (post, diag)
        consola.print(f"modelo [bold]{nombre}[/]: {diag['draws']} draws · r_hat máx {diag['rhat_max']:.3f} · "
                      f"ESS mín {diag['ess_min']:.0f} · {diag['divergencias']} divergencias · {diag['segundos']:.0f} s")

    post = salida["final"][0]
    verdad = con.execute("SELECT * FROM aux_sku_verdad").df()
    rec = E.recuperacion(post, verdad, m.skus)
    cats = pd.DataFrame({
        "categoria": m.categorias,
        "elasticidad_media": post["mu_e"].mean(0), "dispersion": post["sd_e"].mean(0),
        "sustitucion": post["cruz"].mean(0), "encarte": post["enc"].mean(0),
        "post_1": post["post1"].mean(0), "post_2": post["post2"].mean(0),
    })
    diag = pd.DataFrame([dict(modelo=k, **v[1]) for k, v in salida.items()])
    formatos = pd.DataFrame({"formato": FORMATOS, "multiplicador": np.exp(post["dfmt"]).mean(0)})
    guardar(ruta_resultados(), {"elasticidades": rec, "categorias": cats, "diagnostico": diag,
                                "formatos": formatos})
    consola.print(f"elasticidades: correlación con la verdadera {rec.elasticidad.corr(rec.verdadera):.2f} · "
                  f"intervalo 90% cubre {rec.cubre.mean():.0%} de los productos")
    return 0


def cmd_evaluar(args) -> int:
    con = _con()
    if con is None:
        return 1
    if not (ruta_modelos() / "corte.npz").exists():
        consola.print("[red]No hay modelos. Corre primero: python -m elasticidad ajustar[/]")
        return 1
    m = matrices(con)
    post, meta, _ = M.cargar(ruta_modelos(), "corte")
    with consola.status("Evaluando las promociones posteriores al corte..."):
        ev = E.evaluar_promos(con, m, Simulador(post, meta, m), CORTE)
    post, meta, _ = M.cargar(ruta_modelos(), "final")
    with consola.status("Revisando todo el calendario con el modelo final..."):
        retro = E.evaluar_promos(con, m, Simulador(post, meta, m), m.semanas[0])
    res = E.resumen(ev)
    guardar(ruta_resultados(), {"eval_promos": ev, "eval_resumen": res, "retro_promos": retro,
                                "corte": pd.DataFrame({"corte": [CORTE], "fin": [m.semanas[-1]]})})
    mostrar_resumen(res, ev)
    return 0


def mostrar_resumen(res: pd.DataFrame, ev: pd.DataFrame) -> None:
    t = _tabla(f"Promociones de {ev.inicio.min():%d/%m/%Y} a {ev.inicio.max():%d/%m/%Y}: planilla frente a modelo")
    t.add_column("indicador")
    t.add_column("AS IS", justify="right")
    t.add_column("TO BE", justify="right")
    for r in res.itertuples():
        if "S/" in r.indicador:
            a, b = _soles(r.asis), _soles(r.tobe)
        elif r.asis <= 1 and r.tobe <= 1 and "promociones" not in r.indicador:
            a, b = f"{r.asis:.1%}", f"{r.tobe:.1%}"
        else:
            a, b = f"{r.asis:,.0f}", f"{r.tobe:,.0f}"
        t.add_row(r.indicador, a, b)
    consola.print(t)


def cmd_resumen(args) -> int:
    ruta = ruta_resultados()
    if not {"eval_resumen", "eval_promos"} <= tablas(ruta):
        consola.print("[red]No hay resultados. Corre primero: python -m elasticidad evaluar[/]")
        return 1
    mostrar_resumen(leer(ruta, "eval_resumen"), leer(ruta, "eval_promos"))
    return 0


def cmd_simular(args) -> int:
    con = _con()
    if con is None:
        return 1
    if not (ruta_modelos() / "final.npz").exists():
        consola.print("[red]No hay modelo. Corre primero: python -m elasticidad ajustar[/]")
        return 1
    m = matrices(con)
    post, meta, _ = M.cargar(ruta_modelos(), "final")
    sim = Simulador(post, meta, m)
    esc = Escenario(args.sku, pd.Timestamp(args.inicio), args.semanas, args.descuento, args.encarte, args.aporte)
    try:
        r = sim.resumir(esc)
        rec = sim.recomendar(esc)
    except ValueError as e:
        consola.print(f"[red]{e}[/]")
        return 1
    desc = m.skus.set_index("id_sku").loc[args.sku, "descripcion"]
    t = _tabla(f"{desc} · {args.descuento:.0%} · {args.semanas} semana(s) desde {esc.inicio:%d/%m/%Y}")
    t.add_column("")
    t.add_column("", justify="right")
    t.add_row("margen incremental esperado", _soles(r["margen_media"]))
    t.add_row("intervalo 90%", f"{_soles(r['margen_p05'])} a {_soles(r['margen_p95'])}")
    t.add_row("probabilidad de ganar margen", f"{r['prob_gana']:.0%}")
    t.add_row("venta incremental", _soles(r["venta_media"]))
    t.add_row("unidades extra del producto", f"{r['unid_propias']:,.0f}")
    t.add_row("unidades que pierden las otras marcas", f"{r['unid_canibalizadas']:,.0f}")
    t.add_row("unidades que se dejan de vender después", f"{r['unid_post']:,.0f}")
    t.add_row("descuento recomendado", "sin promoción" if rec["descuento"] == 0 else f"{rec['descuento']:.0%}")
    consola.print(t)
    return 0


def cmd_todo(args) -> int:
    for f in (cmd_generar, cmd_ajustar, cmd_evaluar):
        if f(args):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="elasticidad", description="Elasticidad y promociones en Qollqa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre in ("generar", "ajustar", "todo"):
        g = sub.add_parser(nombre)
        g.add_argument("--escala", type=float, default=1.0)
        g.add_argument("--seed", type=int, default=42)
        g.add_argument("--draws", type=int, default=1000)
        g.add_argument("--tune", type=int, default=1000)
    sub.add_parser("evaluar")
    sub.add_parser("resumen")
    s = sub.add_parser("simular")
    s.add_argument("--sku", required=True)
    s.add_argument("--inicio", required=True)
    s.add_argument("--descuento", type=float, required=True)
    s.add_argument("--semanas", type=int, default=1)
    s.add_argument("--encarte", action="store_true")
    s.add_argument("--aporte", type=float, default=0.0)
    args = ap.parse_args(argv)
    return {"generar": cmd_generar, "ajustar": cmd_ajustar, "evaluar": cmd_evaluar, "resumen": cmd_resumen,
            "simular": cmd_simular, "todo": cmd_todo}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
