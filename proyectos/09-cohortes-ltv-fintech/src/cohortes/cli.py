"""
Uso:
    python -m cohortes generar [--escala 0.2]   # datos sintéticos de Ayni
    python -m cohortes cohortes                 # retención, ingreso acumulado y payback por cohorte (SQL)
    python -m cohortes validar                  # ajusta hasta abril 2026 y predice mayo a octubre
    python -m cohortes ltv                      # LTV por canal contra CAC y valor de la base actual
    python -m cohortes todo                     # todo lo anterior
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
from rich.console import Console
from rich.table import Table

from . import ltv as L
from . import validacion as V
from .consultas import conectar
from .resultados import guardar, leer, tablas
from .rutas import RAIZ, ruta_db, ruta_resultados

consola = Console()
CIAN = "#22D3EE"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def mes_corto(fecha) -> str:
    f = pd.Timestamp(fecha)
    return f"{MESES[f.month - 1]} {f.year}"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}", header_style="dim",
                 box=None, padding=(0, 2))


def _con():
    try:
        return conectar(ruta_db())
    except FileNotFoundError as e:
        consola.print(f"[red]{e}[/]")
        return None


def _soles(x: float, dec: int = 2) -> str:
    return "-" if pd.isna(x) else f"S/ {x:,.{dec}f}"


def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    inicio = time.time()
    with consola.status("Generando datos..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    con = conectar(ruta)
    n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("clientes", "transacciones")}
    act = con.execute("SELECT COUNT(fecha_activacion) FROM clientes").fetchone()[0]
    con.close()
    consola.print(f"[bold]{ruta.name}[/] · {n['clientes']:,} registros · {act:,} cuentas activadas · "
                  f"{n['transacciones']:,} transacciones · {time.time() - inicio:.0f} s")
    return 0


def cmd_cohortes(args) -> int:
    con = _con()
    if con is None:
        return 1
    with consola.status("Armando las cohortes en SQL..."):
        res = L.cohortes(con)
    guardar(ruta_resultados(), res)
    r = res["retencion_canal"]
    piv = r.pivot(index="canal", columns="k", values="retencion")
    emp = res["ltv_real_12"].set_index("canal")
    cac = res["tam_cohortes"].groupby("canal")[["gasto", "clientes"]].sum()
    t = _tabla("Retención por mes de vida (ponderada por cohorte)")
    for c in ("Canal", "Mes 1", "Mes 3", "Mes 6", "Mes 12", "Ingreso 12 meses", "CAC histórico"):
        t.add_column(c, justify="left" if c == "Canal" else "right")
    for canal in piv.sort_values(12, ascending=False).index:
        cac_c = cac.loc[canal].gasto / cac.loc[canal].clientes
        t.add_row(canal, *[f"{piv.loc[canal, k]:.0%}" for k in (1, 3, 6)],
                  f"[{CIAN}]{piv.loc[canal, 12]:.0%}[/]", _soles(emp.loc[canal, "ltv_real"]),
                  _soles(cac_c) if cac_c else "-")
    consola.print(t)
    consola.print(f"[dim]  Ingreso 12 meses: cohortes {mes_corto(emp.primera.min())} a "
                  f"{mes_corto(emp.ultima.max())}, ingreso neto acumulado por cuenta activada.[/]\n")
    return 0


def cmd_validar(args) -> int:
    con = _con()
    if con is None:
        return 1
    inicio = time.time()
    with consola.status("Ajustando con datos hasta abril 2026..."):
        res = V.validar(con)
    guardar(ruta_resultados(), res)
    r = res["val_resumen"].iloc[0]
    consola.print(f"[bold {CIAN}]Holdout {r.corte} → {r.fin}[/] [dim]· {r.clientes:,.0f} clientes con compra "
                  f"antes del corte · {time.time() - inicio:.0f} s[/]")
    t = _tabla("Compras (días con ingreso) en los 6 meses siguientes")
    for c in ("Modelo", "Predichas", "Reales", "Error total", "Error medio por cliente"):
        t.add_column(c, justify="left" if c == "Modelo" else "right")
    for g in res["val_general"].itertuples():
        e = f"{g.error_total_pct:+.1%}"
        t.add_row(g.modelo, f"{g.compras_pred:,.0f}", f"{g.compras_real:,.0f}",
                  f"[{CIAN}]{e}[/]" if g.clave == V.ELEGIDO else e, f"{g.mae_cliente:.2f}")
    consola.print(t)
    t = _tabla("Error por canal")
    for c in ("Canal", "BG/NBD sin canal", "BG/NBD con canal", "MBG/NBD con canal", "Ingreso (MBG + GG)"):
        t.add_column(c, justify="left" if c == "Canal" else "right")
    for f in res["val_canal"].itertuples():
        t.add_row(f.canal, f"{f.error_bgnbd:+.1%}", f"{f.error_bgnbd_canal:+.1%}",
                  f"[{CIAN}]{f.error_mbgnbd_canal:+.1%}[/]", f"{f.error_ingreso:+.1%}")
    consola.print(t)
    consola.print(f"[dim]  P(vivo) contra lo que de verdad pasó: Brier {r.brier_bg:.3f} con BG/NBD y "
                  f"{r.brier_mbg:.3f} con MBG/NBD. Con una sola compra siguen vivos el {r.una_compra_vivos:.0%}; "
                  f"BG/NBD les da {r.una_compra_p_bg:.0%} y MBG/NBD {r.una_compra_p_mbg:.0%}.[/]\n")
    return 0


def cmd_ltv(args) -> int:
    con = _con()
    if con is None:
        return 1
    inicio = time.time()
    with consola.status("Ajustando MBG/NBD y Gamma-Gamma con toda la historia..."):
        res = L.calcular(con)
    guardar(ruta_resultados(), res)
    mostrar_ltv(res, time.time() - inicio)
    return 0


def mostrar_ltv(res: dict, seg: float) -> None:
    c = res["cierre"].iloc[0]
    t = _tabla(f"LTV por cuenta activada (ingreso neto descontado al {c.tasa_mensual:.0%} mensual) contra CAC")
    for col in ("Canal", "CAC", "Modelo 12m", "Real 12m", "LTV 24m", "LTV/CAC", "Payback", "% gasto"):
        t.add_column(col, justify="left" if col == "Canal" else "right")
    for r in res["ltv_canales"].itertuples():
        ratio = "-" if pd.isna(r.ltv_cac_24) else f"{r.ltv_cac_24:.2f}"
        if not pd.isna(r.ltv_cac_24):
            ratio = f"[{CIAN}]{ratio}[/]" if r.ltv_cac_24 >= 1 else f"[red]{ratio}[/]"
        pb = "-" if not r.cac else ("> 24" if pd.isna(r.payback_meses) else f"mes {r.payback_meses:.0f}")
        t.add_row(r.canal, _soles(r.cac) if r.cac else "-", _soles(r.ltv_12_sin_descuento), _soles(r.ltv_real_12),
                  _soles(r.ltv_24), ratio, pb, f"{r.participacion_gasto:.0%}")
    consola.print(t)
    consola.print("[dim]  CAC de las cohortes de los últimos seis meses. Modelo 12m y Real 12m sin descontar; "
                  "Real 12m es lo que dejaron las cohortes que ya cumplieron un año. LTV 24m a valor presente.[/]\n")
    s = res["segmentos"].set_index("segmento")
    t = _tabla(f"Base al {c.fin_observacion} · {c.clientes_modelo:,} clientes con al menos una compra")
    for col in ("Segmento", "Clientes", "P(vivo) media", "Valor esperado 12m"):
        t.add_column(col, justify="left" if col == "Segmento" else "right")
    for nombre in L.SEGMENTOS:
        if nombre in s.index:
            f = s.loc[nombre]
            t.add_row(nombre, f"{f.clientes:,.0f}", f"{f.p_vivo:.0%}", _soles(f.valor_12m, 0))
    consola.print(t)
    consola.print(f"\n  [dim]{seg:.0f} s[/]\n")


def cmd_resumen(args) -> int:
    ruta = ruta_resultados()
    if "ltv_canales" not in tablas(ruta):
        consola.print("[red]No hay resultados. Corre primero: python -m cohortes ltv[/]")
        return 1
    nombres = ("ltv_canales", "segmentos", "cierre")
    mostrar_ltv({n: leer(ruta, n) for n in nombres}, 0)
    return 0


def cmd_todo(args) -> int:
    for f in (cmd_generar, cmd_cohortes, cmd_validar, cmd_ltv):
        if f(args):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cohortes", description="Cohortes y valor de vida en la billetera Ayni")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre in ("generar", "todo"):
        g = sub.add_parser(nombre)
        g.add_argument("--escala", type=float, default=1.0)
        g.add_argument("--seed", type=int, default=42)
    for nombre in ("cohortes", "validar", "ltv", "resumen"):
        sub.add_parser(nombre)
    args = ap.parse_args(argv)
    return {"generar": cmd_generar, "cohortes": cmd_cohortes, "validar": cmd_validar, "ltv": cmd_ltv,
            "resumen": cmd_resumen, "todo": cmd_todo}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
