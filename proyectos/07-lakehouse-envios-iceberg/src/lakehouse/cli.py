"""
Uso:
    python -m lakehouse generar [--escala 0.1 --desde 2026-08-15 --hasta 2026-08-24]
    python -m lakehouse correr [--hasta 2026-08-16T06] [--sin-mantenimiento] [--reiniciar]
    python -m lakehouse estado                       # tablas, archivos, snapshots y marca de agua
    python -m lakehouse contrato                     # qué cayó en cuarentena y cuándo
    python -m lakehouse conciliar                    # plata contra origen y contra aplicar el CDC a la mala
    python -m lakehouse viaje --promesa 2026-07-16   # el OTD de ese día visto desde cada mañana
    python -m lakehouse envio 41234                  # historial de un envío
    python -m lakehouse mantener                     # compactar, expirar y borrar huérfanos ahora
    python -m lakehouse comparar-upsert --lotes 124  # upsert por partición vs Table.upsert de pyiceberg
    python -m lakehouse todo                         # generar, correr y conciliar
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import EqualTo
from rich.console import Console
from rich.table import Table

from . import catalogo
from .auditoria import conciliar, ingenuo
from .bitacora import Bitacora
from .calendario import etiqueta_corte, etiqueta_dia
from .cdc import lotes_disponibles
from .contrato import Contrato
from .ingesta import lotes_pendientes
from .mantenimiento import estadisticas
from .pipeline import correr, mantenimiento, preparar
from .rutas import RAIZ, dir_datos, dir_lakehouse, ruta_origen
from .viaje import promesa_por_corte

consola = Console()
CIAN = "#22D3EE"
VERDE, ROJO, AMBAR = "#34D399", "#F87171", "#FBBF24"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}",
                 header_style="dim", box=None, padding=(0, 2))


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


class SinDatos(Exception):
    pass


def _tablas():
    try:
        return catalogo.tablas()
    except NoSuchTableError as e:
        raise SinDatos("No hay lakehouse todavía. Corre `python -m lakehouse correr`.") from e


# ---------------------------------------------------------------- comandos

def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    with consola.status("Generando el CDC de envíos..."):
        r = generar(dir_datos(), escala=args.escala, seed=args.seed, desde=args.desde, hasta=args.hasta)
    consola.print(f"[bold]{r['envios']:,}[/] envíos · {r['eventos']:,} eventos en {r['lotes']} lotes · "
                  f"{r['eventos_tarde']:,} tardíos · {r['eventos_duplicados']:,} duplicados")
    return 0


def cmd_correr(args) -> int:
    if not lotes_disponibles():
        raise SinDatos("No hay archivos CDC. Corre `python -m lakehouse generar`.")
    bit = Bitacora()
    if args.reiniciar:
        shutil.rmtree(dir_lakehouse(), ignore_errors=True)
        bit.reiniciar()
    contrato, t = preparar()
    lotes = lotes_pendientes(t, hasta=args.hasta)
    if not lotes:
        consola.print("[dim]No hay lotes pendientes.[/]")
        return 0
    consola.print(f"Procesando {len(lotes)} lotes: {etiqueta_corte(lotes[0])} a {etiqueta_corte(lotes[-1])}")
    t0 = time.perf_counter()
    filas = []
    with consola.status("") as estado:
        def progreso(f):
            estado.update(f"[{CIAN}]{etiqueta_corte(f['lote'])}[/] · {f['eventos']:,} eventos · "
                          f"{f['cuarentena']} en cuarentena · {time.perf_counter() - t0:.0f} s")
            if f["columnas_nuevas"]:
                consola.print(f"  [{AMBAR}]esquema[/] {etiqueta_corte(f['lote'])}: plata.envios agrega "
                              f"{f['columnas_nuevas']}")
            if f["no_declaradas"]:
                consola.print(f"  [{AMBAR}]aviso[/] {etiqueta_corte(f['lote'])}: columnas fuera del contrato: "
                              f"{f['no_declaradas']} (quedan solo en bronce)")
            filas.append(f)
        correr(t, contrato, lotes, con_mantenimiento=not args.sin_mantenimiento, bitacora=bit, progreso=progreso)
    df = pd.DataFrame(filas)
    seg = time.perf_counter() - t0
    tb = _tabla(f"{len(df)} lotes en {seg:.0f} s ({seg / len(df):.2f} s por lote)")
    for c in ("", "eventos"):
        tb.add_column(c, justify="right" if c else "left")
    for etiqueta, col in [("Eventos leídos", "eventos"), ("Duplicados descartados", "duplicados"),
                          ("Llegaron en un lote posterior", "tardios"),
                          ("Ignorados por lsn (más viejos que plata)", "descartados_lsn"),
                          ("En cuarentena", "cuarentena"), ("Insertados en plata", "insertados"),
                          ("Actualizados", "actualizados"), ("Borrados", "borrados"),
                          ("Cambios de estado al historial", "transiciones")]:
        tb.add_row(etiqueta, f"{int(df[col].sum()):,}")
    consola.print(tb)
    alertas = df[(df["eventos"] - df["duplicados"]) > 0]
    alertas = alertas[alertas["cuarentena"] / (alertas["eventos"] - alertas["duplicados"]) > contrato.umbral_cuarentena]
    if len(alertas):
        consola.print(f"[{ROJO}]  {len(alertas)} lotes superan el umbral de cuarentena "
                      f"({_pct(contrato.umbral_cuarentena)}): "
                      + ", ".join(etiqueta_corte(x) for x in alertas["lote"].head(8))
                      + (" ..." if len(alertas) > 8 else "") + "[/]")
    consola.print()
    return 0


def cmd_estado(args) -> int:
    t = _tablas()
    tb = _tabla("Tablas del lakehouse")
    for c in ("Tabla", "Filas", "Archivos", "MB", "Manifiestos", "Snapshots", "metadata.json", "Último lote"):
        tb.add_column(c, justify="left" if c in ("Tabla", "Último lote") else "right")
    for k, nombre in [("bronce", "bronce.cdc_envios"), ("plata", "plata.envios"), ("estados", "plata.estados_envio"),
                      ("cuarentena", "plata.cuarentena"), ("oro", "oro.entregas_diarias")]:
        e = estadisticas(t[k], medir_lectura=False)
        lote = catalogo.ultimo_lote(t[k])
        tb.add_row(f"[{CIAN}]{nombre}[/]", f"{e.filas:,}", str(e.archivos_datos), f"{e.mb_datos:.1f}",
                   str(e.manifiestos), str(e.snapshots), f"{e.kb_metadata_json:.0f} KB",
                   etiqueta_corte(lote) if lote else "-")
    consola.print(tb)
    tags = [n for n in t["oro"].refs() if n.startswith("corte-")]
    consola.print(f"[dim]  oro tiene {len(tags)} cortes etiquetados para viajar en el tiempo. "
                  f"Esquema de plata: {len(t['plata'].schema().fields)} columnas, "
                  f"versión {len(t['plata'].schemas())}.[/]\n")
    return 0


def cmd_contrato(args) -> int:
    contrato = Contrato.desde_yaml()
    t = _tablas()
    q = t["cuarentena"].scan().to_pandas()
    consola.print(f"[bold]Contrato {contrato.contrato} v{contrato.version}[/] · dueño: {contrato.dueno} · "
                  f"{len(contrato.chequeos())} chequeos")
    if q.empty:
        consola.print("[dim]  Nada en cuarentena.[/]\n")
        return 0
    q = q.explode("violaciones")
    g = q.groupby("violaciones").agg(eventos=("lsn", "size"), envios=("id_envio", "nunique"),
                                     primero=("lote", "min"), ultimo=("lote", "max"),
                                     lotes=("lote", "nunique")).sort_values("eventos", ascending=False)
    tb = _tabla("Eventos en cuarentena por regla")
    for c in ("Regla", "Eventos", "Envíos", "Lotes", "Primer lote", "Último lote"):
        tb.add_column(c, justify="left" if c in ("Regla", "Primer lote", "Último lote") else "right")
    for regla, f in g.iterrows():
        tb.add_row(f"[{AMBAR}]{regla}[/]", f"{f.eventos:,}", f"{f.envios:,}", str(f.lotes),
                   etiqueta_corte(f.primero), etiqueta_corte(f.ultimo))
    consola.print(tb)
    ej = q[q["violaciones"] == g.index[0]].head(1)
    if len(ej):
        consola.print(f"[dim]  ejemplo ({g.index[0]}): {ej.iloc[0]['despues'][:150]}...[/]", highlight=False)
    consola.print()
    return 0


def cmd_conciliar(args) -> int:
    contrato = Contrato.desde_yaml()
    t = _tablas()
    if not ruta_origen().exists():
        raise SinDatos("No está el origen (datos/origen/envios.parquet). Corre `generar`.")
    with consola.status("Conciliando plata con origen..."):
        c = conciliar(t["plata"], t["cuarentena"], contrato)
        m = ingenuo(t["bronce"], t["plata"], contrato)
    ok = c["sobran_en_plata"] == 0 and not c["columnas_distintas"] and \
        c["faltan_en_plata"] == c["faltan_explicados_por_cuarentena"]
    tb = _tabla("Conciliación plata.envios vs origen")
    tb.add_column("")
    tb.add_column("envíos", justify="right")
    tb.add_row("En origen", f"{c['origen']:,}")
    tb.add_row("En plata", f"{c['plata']:,}")
    tb.add_row("Faltan en plata", f"{c['faltan_en_plata']:,}")
    tb.add_row("  ...todos sus eventos en cuarentena", f"{c['faltan_explicados_por_cuarentena']:,}")
    tb.add_row("Sobran en plata", f"{c['sobran_en_plata']:,}")
    tb.add_row("Con alguna columna distinta", f"{sum(c['columnas_distintas'].values()):,}")
    consola.print(tb)
    consola.print("[dim]  reglas que rompen los faltantes (un envío puede romper varias): " + ", ".join(
        f"{r.regla} {r.envios}" for r in c["motivos_faltantes"].itertuples()) + "[/]", highlight=False)
    consola.print(f"  [{VERDE if ok else ROJO}]{'cuadra' if ok else 'no cuadra'}[/]\n")

    tb = _tabla("CDC aplicado en orden de llegada, sin lsn ni contrato")
    tb.add_column("")
    tb.add_column("envíos", justify="right")
    tb.add_row("Estado final distinto al de origen", f"[{ROJO}]{m['estado_distinto']:,}[/]")
    tb.add_row("  ...entregados que no figuran como entregados", f"{m['entregados_que_no_figuran']:,}")
    tb.add_row("Estado distinto en plata (con lsn)", f"[{VERDE}]{m['plata_estado_distinto']:,}[/]")
    consola.print(tb)
    for r in m["cruce"].head(5).itertuples():
        consola.print(f"[dim]  origen {r.en_origen} -> a la mala {r.a_la_mala}: {r.envios}[/]")
    consola.print()
    return 0 if ok else 1


def cmd_viaje(args) -> int:
    t = _tablas()
    df = promesa_por_corte(t["oro"], args.promesa)
    if df.empty:
        raise SinDatos(f"No hay cortes posteriores a {args.promesa} con esa promesa.")
    tb = _tabla(f"Promesas del {etiqueta_dia(args.promesa, True)} vistas desde cada corte de las 06:00")
    for c in ("Corte", "Comprometidos", "Entregados", "A tiempo", "Pendientes", "OTD"):
        tb.add_column(c, justify="left" if c == "Corte" else "right")
    previo = None
    for f in df.head(args.cortes).itertuples():
        cambio = "" if previo is None else f"  [dim]{(f.otd - previo) * 100:+.1f} pp[/]"
        tb.add_row(etiqueta_dia(f.corte), f"{f.comprometidos:,}", f"{f.entregados:,}", f"{f.a_tiempo:,}",
                   f"{f.pendientes:,}", f"[{CIAN}]{_pct(f.otd)}[/]{cambio}")
        previo = f.otd
    consola.print(tb)
    ult = df.iloc[-1]
    consola.print(f"[dim]  Último corte ({etiqueta_dia(ult.corte)}): OTD {_pct(ult.otd)}. "
                  f"La mañana siguiente se reportó {_pct(df.iloc[0].otd)}.[/]\n")
    return 0


def cmd_envio(args) -> int:
    t = _tablas()
    h = t["estados"].scan(row_filter=EqualTo("id_envio", args.id)).to_pandas().sort_values("desde")
    p = t["plata"].scan(row_filter=EqualTo("id_envio", args.id)).to_pandas()
    q = t["cuarentena"].scan(row_filter=EqualTo("id_envio", args.id)).to_pandas()
    if h.empty and p.empty and q.empty:
        raise SinDatos(f"El envío {args.id} no está en el lakehouse.")
    if len(p):
        f = p.iloc[0]
        consola.print(f"[bold]{f.codigo_seguimiento}[/] · {f.distrito} · {f.servicio} · promesa "
                      f"{etiqueta_dia(f.fecha_promesa, True)} · estado [{CIAN}]{f.estado}[/] · lsn {f._lsn}")
    tb = _tabla("Historial de estados")
    for c in ("Desde", "Estado", "lsn", "Llegó en el lote"):
        tb.add_column(c)
    for f in h.itertuples():
        tb.add_row(f"{f.desde:%d/%m %H:%M}", f.estado, str(f.lsn), etiqueta_corte(f.lote))
    consola.print(tb)
    for f in q.itertuples():
        consola.print(f"[{AMBAR}]  cuarentena[/] lsn {f.lsn} ({etiqueta_corte(f.lote)}): {', '.join(f.violaciones)}")
    consola.print()
    return 0


def cmd_mantener(args) -> int:
    t = _tablas()
    lote = catalogo.ultimo_lote(t["bronce"])
    filas = mantenimiento(t, lote)
    Bitacora().mantenimiento(filas)
    tb = _tabla("Mantenimiento")
    for c in ("Tabla", "Archivos", "Snapshots", "Huérfanos borrados", "Segundos"):
        tb.add_column(c, justify="left" if c == "Tabla" else "right")
    for f in filas:
        tb.add_row(f["tabla"], f"{f['antes_archivos_datos']} -> {f['despues_archivos_datos']}",
                   f"{f['antes_snapshots']} -> {f['despues_snapshots']}", str(f["huerfanos_borrados"]),
                   f"{f['segundos']:.1f}")
    consola.print(tb)
    return 0


def cmd_comparar(args) -> int:
    import tempfile

    from .comparar import comparar_upsert

    if not lotes_disponibles():
        raise SinDatos("No hay archivos CDC. Corre `python -m lakehouse generar`.")
    with tempfile.TemporaryDirectory() as d, consola.status(f"Corriendo {args.lotes} lotes con las dos variantes..."):
        df = comparar_upsert(Contrato.desde_yaml(), Path(d), args.lotes)
    tb = _tabla("plata.envios: upsert por partición vs Table.upsert (segundos por lote)")
    for c in ("Lotes", "Filas en plata al final", "Por partición", "Table.upsert"):
        tb.add_column(c, justify="right")
    for i in range(0, len(df), 28):
        g = df.iloc[i:i + 28]
        tb.add_row(f"{i + 1}-{i + len(g)}", f"{g.filas_tabla.iloc[-1]:,}", f"{g.seg_particion.mean():.2f}",
                   f"{g.seg_upsert.mean():.2f}")
    tb.add_row("[bold]total[/]", "", f"[bold]{df.seg_particion.sum():.0f} s[/]",
               f"[bold]{df.seg_upsert.sum():.0f} s[/]")
    consola.print(tb)
    return 0


def cmd_todo(args) -> int:
    cmd_generar(args)
    args.reiniciar, args.hasta, args.sin_mantenimiento = True, None, False
    cmd_correr(args)
    cmd_contrato(args)
    return cmd_conciliar(args)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lakehouse", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)

    def gen(s):
        s.add_argument("--escala", type=float, default=1.0)
        s.add_argument("--seed", type=int, default=26)
        s.add_argument("--desde", type=date.fromisoformat, default=date(2026, 7, 1))
        s.add_argument("--hasta", type=date.fromisoformat, default=date(2026, 10, 31))

    gen(sub.add_parser("generar", help="CDC sintético y origen final"))
    s = sub.add_parser("correr", help="procesa los lotes pendientes")
    s.add_argument("--hasta", help="último lote a procesar, ej. 2026-08-16T06")
    s.add_argument("--sin-mantenimiento", action="store_true")
    s.add_argument("--reiniciar", action="store_true", help="borra el lakehouse y empieza de cero")
    sub.add_parser("estado")
    sub.add_parser("contrato")
    sub.add_parser("conciliar")
    s = sub.add_parser("viaje")
    s.add_argument("--promesa", type=date.fromisoformat, required=True)
    s.add_argument("--cortes", type=int, default=8)
    s = sub.add_parser("envio")
    s.add_argument("id", type=int)
    sub.add_parser("mantener")
    s = sub.add_parser("comparar-upsert", help="mide Table.upsert contra el upsert por partición")
    s.add_argument("--lotes", type=int, default=124)
    gen(sub.add_parser("todo", help="generar, correr y conciliar"))

    args = p.parse_args(argv)
    comandos = {"generar": cmd_generar, "correr": cmd_correr, "estado": cmd_estado, "contrato": cmd_contrato,
                "conciliar": cmd_conciliar, "viaje": cmd_viaje, "envio": cmd_envio, "mantener": cmd_mantener,
                "comparar-upsert": cmd_comparar,
                "todo": cmd_todo}
    try:
        return comandos[args.comando](args)
    except SinDatos as e:
        consola.print(f"[{ROJO}]{e}[/]")
        return 1


