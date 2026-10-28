"""
Uso:
    python -m demanda generar [--escala 0.25]     # datos sintéticos
    python -m demanda backtest [--cortes 13]      # entrena en cada corte y mide el error
    python -m demanda reposicion                  # simula la regla actual vs. el pronóstico
    python -m demanda pronostico [--local 3]      # pronóstico vigente y pedido sugerido
    python -m demanda todo                        # los cuatro pasos
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
from rich.console import Console
from rich.table import Table

from . import backtest as bt_mod
from . import reposicion as rep
from .datos import cargar
from .pronostico import en_transito, pedido_sugerido, pronosticar
from .resultados import cargar_backtest, guardar, guardar_backtest
from .rutas import RAIZ, ruta_db, ruta_resultados

consola = Console()
CIAN = "#22D3EE"
NOMBRES = {"promedio_28": "Promedio 28 días (regla actual)", "naive_estacional": "Naive estacional",
           "lgbm_sin_tratar": "LightGBM sin tratar quiebres", "lgbm": "LightGBM"}
POLITICAS = {"regla_actual": "Regla actual (prom. 28 d)", "pronostico": "Pronóstico (sin margen)",
             "pronostico_p90": "Pronóstico + margen P90", "pronostico_p95": "Pronóstico + margen P95"}


def _pct(x, signo=False) -> str:
    if x is None or pd.isna(x):
        return "-"
    return f"{x:+.1%}" if signo else f"{x:.1%}"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}",
                 header_style="dim", box=None, padding=(0, 2))


def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    with consola.status("Generando datos..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    b = cargar(ruta)
    q = b.ventas.stock_cierre.eq(0).mean()
    consola.print(f"[bold]{ruta.name}[/] · {len(b.locales)} locales · {len(b.productos)} productos · "
                  f"{len(b.ventas):,} filas · {b.ventas.fecha.min():%d/%m/%Y} a {b.ultimo_dia:%d/%m/%Y} · "
                  f"quiebre en [{CIAN}]{q:.1%}[/] de los días")
    return 0


def cmd_backtest(args) -> int:
    base = cargar(ruta_db(), con_latente=True)
    cortes = bt_mod.cortes_por_defecto(base, n=args.cortes)
    inicio = time.time()
    with consola.status("Backtest...") as estado:
        def avance(i, n, c):
            estado.update(f"Corte {i + 1}/{n} · {c:%d/%m/%Y} · entrenando 2 LightGBM")
        bt = bt_mod.correr(base, cortes, rondas=args.rondas, progreso=avance)
    vigentes = bt_mod.calibradores_vigentes(bt)
    ruta = ruta_resultados()
    if ruta.exists():
        ruta.unlink()
    guardar_backtest(ruta, bt, vigentes)

    modelos = bt_mod.tabla_modelos(bt.predicciones, base.latente)
    segmentos = bt_mod.tabla_segmentos(bt.predicciones, "segmento")
    categorias = bt_mod.tabla_segmentos(bt.predicciones, "categoria")
    cob = bt_mod.tabla_cobertura(bt.predicciones)
    guardar(ruta, {"metricas_modelos": modelos, "metricas_segmentos": segmentos,
                   "metricas_categorias": categorias, "cobertura_intervalos": cob,
                   "corrida": pd.DataFrame([{"fecha": pd.Timestamp.now().floor("s"),
                                             "cortes": len(cortes), "primer_corte": cortes[0],
                                             "ultimo_corte": cortes[-1], "segundos": time.time() - inicio,
                                             "filas": len(bt.predicciones)}])})
    mostrar_backtest(modelos, segmentos, cob, cortes, time.time() - inicio)
    return 0


def mostrar_backtest(modelos, segmentos, cob, cortes, segundos) -> None:
    t = _tabla(f"Backtest · {len(cortes)} cortes ({cortes[0]:%d/%m} a {cortes[-1]:%d/%m/%Y}) · 14 días")
    t.add_column("Modelo")
    t.add_column("WAPE diario", justify="right")
    t.add_column("WAPE semanal", justify="right")
    t.add_column("Sesgo", justify="right")
    t.add_column("Sesgo en quiebres", justify="right")
    mejor = modelos.wape.min()
    for r in modelos.itertuples():
        estilo = f"bold {CIAN}" if r.wape == mejor else ""
        t.add_row(NOMBRES[r.modelo], f"[{estilo}]{_pct(r.wape)}[/]" if estilo else _pct(r.wape),
                  _pct(r.wape_semana), _pct(r.sesgo, True), _pct(getattr(r, "sesgo_en_quiebres", None), True))
    consola.print(t)
    consola.print("[dim]  WAPE y sesgo contra la venta en días sin quiebre; sesgo en quiebres contra la "
                  "demanda latente.[/]\n")

    t = _tabla("Por rotación")
    for c in ("Segmento", "Unidades", "WAPE regla actual", "WAPE LightGBM", "Mejora"):
        t.add_column(c, justify="left" if c == "Segmento" else "right")
    for r in segmentos.sort_values("unidades", ascending=False).itertuples():
        t.add_row(r.segmento, f"{r.unidades:,.0f}", _pct(r.wape_promedio_28), _pct(r.wape_lgbm),
                  f"[{CIAN}]{_pct(r.mejora, True)}[/]")
    consola.print(t)

    total = cob[cob.segmento == "total"].iloc[0]
    consola.print(f"\n  Intervalo P10-P90 (conformal): cubre [{CIAN}]{total.cobertura:.1%}[/] de los días "
                  f"[dim](objetivo 80%)[/] · {segundos:.0f} s\n")


def cmd_reposicion(args) -> int:
    base = cargar(ruta_db(), con_latente=True)
    bt, _ = cargar_backtest(ruta_resultados())
    filas, cat, diario = [], [], []
    with consola.status("Simulando políticas..."):
        for pol in rep.POLITICAS:
            sim = rep.simular(base, bt, pol)
            filas.append(rep.indicadores(sim, base))
            cat.append(rep.indicadores(sim, base, por="categoria"))
            d = sim.diario.merge(base.productos[["id_producto", "costo"]], on="id_producto")
            d["inv"] = d.stock_cierre * d.costo
            d["q"] = d.stock_cierre.eq(0)
            diario.append(d.groupby("fecha").agg(inventario=("inv", "sum"), quiebres=("q", "mean"),
                                                 demanda=("demanda", "sum"), venta=("venta", "sum"))
                          .reset_index().assign(politica=pol))
    resumen = pd.concat(filas, ignore_index=True)
    guardar(ruta_resultados(), {"simulacion_resumen": resumen,
                                "simulacion_categorias": pd.concat(cat, ignore_index=True),
                                "simulacion_diaria": pd.concat(diario, ignore_index=True)})
    mostrar_reposicion(resumen, sim.inicio, sim.fin)
    return 0


def mostrar_reposicion(resumen: pd.DataFrame, inicio, fin) -> None:
    t = _tabla(f"Reposición simulada · {inicio:%d/%m} a {fin:%d/%m/%Y}")
    for c in ("Política", "Nivel de servicio", "Días con quiebre", "Venta perdida", "Inventario prom.",
              "Días de inventario"):
        t.add_column(c, justify="left" if c == "Política" else "right")
    for r in resumen.itertuples():
        t.add_row(POLITICAS[r.politica], _pct(r.nivel_servicio), _pct(r.dias_con_quiebre),
                  f"S/ {r.venta_perdida:,.0f}", f"S/ {r.inventario_promedio:,.0f}", f"{r.dias_de_inventario:.1f}")
    consola.print(t)
    a = resumen.set_index("politica")
    if {"regla_actual", "pronostico_p95"} <= set(a.index):
        dinv = a.loc["pronostico_p95", "inventario_promedio"] / a.loc["regla_actual", "inventario_promedio"] - 1
        dper = a.loc["pronostico_p95", "venta_perdida"] / a.loc["regla_actual", "venta_perdida"] - 1
        consola.print(f"\n  Con margen P95: inventario [{CIAN}]{dinv:+.1%}[/] · venta perdida "
                      f"[{CIAN}]{dper:+.1%}[/] frente a la regla actual\n")


def cmd_pronostico(args) -> int:
    base = cargar(ruta_db())
    _, (cal_d, cal_s) = cargar_backtest(ruta_resultados())
    with consola.status("Entrenando con toda la historia..."):
        fut = pronosticar(base, cal_d, rondas=args.rondas)
    ped = pedido_sugerido(base, fut, cal_s, en_transito(ruta_db(), base.ultimo_dia))
    guardar(ruta_resultados(), {"pronostico": fut, "pedido_sugerido": ped})
    mostrar_pedido(base, ped, args.local, args.top)
    return 0


def mostrar_pedido(base, ped: pd.DataFrame, id_local: int, top: int = 12) -> None:
    loc = base.locales.set_index("id_local").loc[id_local]
    p = ped[ped.id_local == id_local]
    t = _tabla(f"Pedido sugerido · {loc.nombre} · corte {base.ultimo_dia:%d/%m/%Y} · cubre "
               f"{6 + loc.lead_time_dias} días")
    for c in ("Producto", "Demanda esperada", "Stock", "En tránsito", "Objetivo P95", "Pedido"):
        t.add_column(c, justify="left" if c == "Producto" else "right")
    top_ = p[p.pedido > 0].sort_values("costo_pedido", ascending=False).head(top)
    for r in top_.itertuples():
        t.add_row(r.nombre, f"{r.demanda_esperada:.1f}", str(r.stock_cierre), str(r.en_transito),
                  str(int(r.stock_objetivo)), f"[bold {CIAN}]{r.pedido}[/]")
    consola.print(t)
    consola.print(f"[dim]  {int((p.pedido > 0).sum())} de {len(p)} productos con pedido · "
                  f"S/ {p.costo_pedido.sum():,.0f} al costo · lista completa en la tabla pedido_sugerido[/]")


def cmd_todo(args) -> int:
    for f in (cmd_generar, cmd_backtest, cmd_reposicion, cmd_pronostico):
        if f(args):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demanda", description="Pronóstico de demanda y reposición.")
    sub = parser.add_subparsers(dest="comando", required=True)

    def _comunes(p, generar=False, backtest=False, local=False):
        if generar:
            p.add_argument("--escala", type=float, default=1.0)
            p.add_argument("--seed", type=int, default=42)
        if backtest:
            p.add_argument("--cortes", type=int, default=13)
        p.add_argument("--rondas", type=int, default=None, help="Rondas de LightGBM (por defecto 500)")
        if local:
            p.add_argument("--local", type=int, default=1)
            p.add_argument("--top", type=int, default=12)

    _comunes(sub.add_parser("generar", help="Genera los datos sintéticos"), generar=True)
    _comunes(sub.add_parser("backtest", help="Backtest con origen móvil"), backtest=True)
    _comunes(sub.add_parser("reposicion", help="Simula políticas de reposición"))
    _comunes(sub.add_parser("pronostico", help="Pronóstico vigente y pedido sugerido"), local=True)
    _comunes(sub.add_parser("todo", help="Los cuatro pasos"), generar=True, backtest=True, local=True)

    args = parser.parse_args(argv)
    comandos = {"generar": cmd_generar, "backtest": cmd_backtest, "reposicion": cmd_reposicion,
                "pronostico": cmd_pronostico, "todo": cmd_todo}
    try:
        return comandos[args.comando](args)
    except FileNotFoundError as e:
        consola.print(f"[red]{e}[/]")
        return 1
