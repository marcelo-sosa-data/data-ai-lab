"""
Uso:
    python -m comprobantes generar [--escala 0.1]
    python -m comprobantes leer --demo          # Tesseract sobre todos los comprobantes
    python -m comprobantes leer --n 60          # muestra de octubre con el LLM de .env
    python -m comprobantes evaluar [--corrida demo]
    python -m comprobantes ver 125 --demo       # lee uno en vivo: campos, validaciones y destino
    python -m comprobantes resumen
    python -m comprobantes todo                 # generar, leer --demo y evaluar
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
from rich.console import Console
from rich.table import Table

from .rutas import RAIZ, ruta_db, ruta_imagenes, ruta_resultados

consola = Console()
MES_CALIBRACION, MES_PRUEBA = 9, 10


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ruta)
    except ImportError:
        pass


def nombre_corrida(demo: bool) -> str:
    if demo:
        return "demo"
    modelo = os.getenv("LLM_MODELO", "llm")
    return "llm_" + "".join(c if c.isalnum() else "_" for c in modelo.lower())


def _leer_base(db: Path) -> tuple:
    from .procesar import cargar_contexto

    con = duckdb.connect(str(db), read_only=True)
    recepcion = con.execute("SELECT * FROM recepcion ORDER BY doc_id").df()
    verdad = con.execute("SELECT * FROM aux_verdad ORDER BY doc_id").df()
    ctx = cargar_contexto(con)
    con.close()
    return recepcion, verdad, ctx


def _guardar(nombre: str, df: pd.DataFrame, corrida: str) -> None:
    ruta = ruta_resultados()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ruta))
    df = df.assign(corrida=corrida)
    con.register("t", df)
    existe = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [nombre]).fetchone()[0]
    if existe:
        con.execute(f"DELETE FROM {nombre} WHERE corrida = ?", [corrida])
        con.execute(f"INSERT INTO {nombre} BY NAME SELECT * FROM t")
    else:
        con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM t")
    con.close()


def _cargar(nombre: str, corrida: str) -> pd.DataFrame:
    con = duckdb.connect(str(ruta_resultados()), read_only=True)
    df = con.execute(f"SELECT * FROM {nombre} WHERE corrida = ?", [corrida]).df()
    con.close()
    return df


# ------------------------------------------------------------------ comandos

def cmd_generar(args) -> None:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    t = time.perf_counter()
    with consola.status("Generando comprobantes e imágenes..."):
        ruta = generar(ruta_db(), escala=args.escala, seed=args.seed)
    con = duckdb.connect(str(ruta), read_only=True)
    n, anom = con.execute("SELECT COUNT(*), COUNT(anomalia) FROM aux_verdad").fetchone()
    consola.print(f"{n:,} comprobantes, {anom} con error del proveedor · {time.perf_counter() - t:.0f} s")


def cmd_leer(args) -> None:
    from .procesar import leer_lote

    recepcion, verdad, _ = _leer_base(ruta_db())
    extractor = None
    if not args.demo:
        from .llm import ExtractorLLM
        extractor = ExtractorLLM(args.modelo)
        if args.n:
            oct_ = recepcion[pd.to_datetime(recepcion["fecha_recepcion"]).dt.month == MES_PRUEBA]
            recepcion = (oct_.groupby("captura", group_keys=False)
                         .apply(lambda g: g.sample(min(len(g), max(1, round(args.n * len(g) / len(oct_)))),
                                                   random_state=14)))
    corrida = nombre_corrida(args.demo)
    t = time.perf_counter()
    with consola.status("Leyendo...") as estado:
        lecturas = leer_lote(recepcion, ruta_imagenes(), extractor, args.procesos,
                             lambda i, n: estado.update(f"Leyendo {i}/{n}"))
    _guardar("lecturas", lecturas, corrida)
    consola.print(f"{len(lecturas):,} comprobantes leídos con {lecturas['extractor'].iloc[0]} "
                  f"en {time.perf_counter() - t:.0f} s ({lecturas['segundos'].mean():.2f} s por comprobante)")
    if extractor is not None:
        consola.print(f"tokens: {extractor.tokens_entrada:,} entrada / {extractor.tokens_salida:,} salida")


def evaluar(corrida: str = "demo") -> dict:
    from . import evaluacion as ev
    from .procesar import rutear

    recepcion, verdad, ctx = _leer_base(ruta_db())
    lecturas = _cargar("lecturas", corrida).drop(columns="corrida")
    recepcion = recepcion[recepcion["doc_id"].isin(lecturas["doc_id"])]
    ac = ev.aciertos(lecturas, verdad)
    usa_conf = corrida == "demo"
    mes = pd.to_datetime(recepcion["fecha_recepcion"]).dt.month

    if usa_conf and (mes == MES_CALIBRACION).any():
        cal = recepcion[mes == MES_CALIBRACION]
        curva = ev.curva_umbral(lecturas[lecturas["doc_id"].isin(cal["doc_id"])], cal, ctx, verdad, ac)
        percentil, umbral = ev.elegir_umbral(curva)
    else:
        curva, percentil, umbral = pd.DataFrame(), None, 0.0
    dec = rutear(lecturas, recepcion, ctx, umbral, verdad, usar_confianza=usa_conf)

    prueba = ac[ac["mes"] == MES_PRUEBA]["doc_id"]
    dec_p, ac_p = dec[dec["doc_id"].isin(prueba)], ac[ac["doc_id"].isin(prueba)]
    ver_p = verdad[verdad["doc_id"].isin(prueba)]
    # solo validaciones, sin confianza: es como se rutea con un LLM
    dec_sin = rutear(lecturas, recepcion, ctx, umbral, verdad, usar_confianza=False)
    dec_sin = dec_sin[dec_sin["doc_id"].isin(prueba)]
    resumen = {
        "corrida": corrida, "extractor": lecturas["extractor"].iloc[0], "percentil": percentil, "umbral": umbral,
        "segundos_por_comprobante": float(lecturas["segundos"].mean()),
        "exactitud_campos_prueba": ac_p[ev.CAMPOS].mean().to_dict(),
        "exactitud_media_prueba": float(ac_p[ev.CAMPOS].to_numpy().mean()),
        "docs_correctos_prueba": float(ac_p["doc_correcto"].mean()),
        "ruteo_prueba": ev.metricas_ruteo(dec_p, ac_p, ver_p),
        "ruteo_prueba_sin_confianza": ev.metricas_ruteo(dec_sin, ac_p, ver_p),
        "proceso_prueba": ev.as_is_vs_to_be(dec_p, ver_p, ac_p),
        "deteccion_prueba": ev.deteccion_por_anomalia(dec_p, ver_p).reset_index().to_dict("records"),
    }
    _guardar("aciertos", ac, corrida)
    _guardar("decisiones", dec, corrida)
    if len(curva):
        _guardar("curva_umbral", curva, corrida)
    _guardar("resumen", pd.DataFrame([{"datos": json.dumps(resumen, default=str, ensure_ascii=False)}]), corrida)
    return resumen


def cmd_evaluar(args) -> None:
    with consola.status("Validando y ruteando..."):
        res = evaluar(args.corrida)
    mostrar_resumen(res)


def mostrar_resumen(res: dict) -> None:
    r, p = res["ruteo_prueba"], res["proceso_prueba"]
    if res["percentil"] is not None:
        consola.print(f"[bold]{res['extractor']}[/] · umbral por campo en el percentil {res['percentil']:.0%} "
                      "de las lecturas correctas de setiembre")
    else:
        consola.print(f"[bold]{res['extractor']}[/] · ruteo solo con validaciones")
    t = Table(title="Exactitud por campo, octubre", header_style="bold")
    t.add_column("campo")
    t.add_column("exactitud", justify="right")
    for k, v in res["exactitud_campos_prueba"].items():
        t.add_row(k, f"{v:.1%}")
    consola.print(t)
    consola.print(f"Comprobantes leídos sin ningún error: {res['docs_correctos_prueba']:.1%}")
    consola.print(f"Aprobados solos: {r['aprobados']} de {r['comprobantes']} ({r['pct_aprobados']:.1%}); "
                  f"con algún campo mal: {r['aprobados_con_error']} ({r['tasa_error_aprobados']:.2%})")
    t = Table(title="Proceso, octubre", header_style="bold")
    for c in ("indicador", "AS IS", "TO BE"):
        t.add_column(c, justify="right" if c != "indicador" else "left")
    a, b = p["as_is"], p["to_be"]
    t.add_row("comprobantes que se digitan", f"{a['pct_digitado']:.0%}", f"{b['pct_digitado']:.1%}")
    t.add_row("errores detectados antes de pagar", f"{a['detectadas_antes_de_pagar']} de {p['con_anomalia']}",
              f"{b['detectadas_antes_de_pagar']} de {p['con_anomalia']}")
    t.add_row("días de recepción a detección", f"{a['dias_a_deteccion']:.1f}", f"{b['dias_a_deteccion']:.1f}")
    t.add_row("pagados sin detectar", f"{a['pagadas_sin_detectar']} (S/ {a['monto_pagado_sin_detectar']:,.0f})",
              f"{b['pagadas_sin_detectar']} (S/ {b['monto_pagado_sin_detectar']:,.0f})")
    consola.print(t)
    t = Table(title="Errores del proveedor en octubre", header_style="bold")
    for c in ("anomalía", "n", "a revisión", "motivo al leer", "motivo tras corregir"):
        t.add_column(c)
    for d in res["deteccion_prueba"]:
        t.add_row(d["anomalia"], str(d["n"]), str(d["a_revision"]), str(d["motivo_al_leer"]), str(d["con_motivo"]))
    consola.print(t)


def cmd_resumen(args) -> None:
    df = _cargar("resumen", args.corrida)
    if df.empty:
        consola.print("[red]No hay resultados. Corre primero `leer` y `evaluar`.[/]")
        raise SystemExit(1)
    mostrar_resumen(json.loads(df["datos"].iloc[0]))


def umbral_guardado(corrida: str = "demo") -> dict | float:
    """El umbral calibrado en la última evaluación; sin evaluación, solo deciden las validaciones."""
    try:
        df = _cargar("resumen", corrida)
        return json.loads(df["datos"].iloc[0])["umbral"] if len(df) else 0.0
    except (duckdb.Error, KeyError):
        return 0.0


def cmd_ver(args) -> None:
    from .procesar import cargar_contexto
    from .reglas import validar
    from .ruteo import decidir

    con = duckdb.connect(str(ruta_db()), read_only=True)
    ctx = cargar_contexto(con)
    fila = con.execute("SELECT archivo, fecha_recepcion FROM recepcion WHERE doc_id = ?", [args.doc_id]).fetchone()
    con.close()
    if fila is None:
        consola.print(f"[red]No existe el comprobante {args.doc_id}[/]")
        raise SystemExit(1)
    if args.demo:
        from .ocr import ExtractorOCR
        ext = ExtractorOCR()
    else:
        from .llm import ExtractorLLM
        ext = ExtractorLLM(args.modelo)
    lec = ext.extraer(ruta_imagenes() / fila[0])
    ctx.fecha_recepcion = pd.Timestamp(fila[1]).date()
    obs = validar(lec.comprobante, ctx)
    dec = decidir(lec.comprobante, lec.confianza, obs, umbral_guardado())
    t = Table(title=f"{fila[0]} · {lec.extractor}", header_style="bold")
    for c in ("campo", "valor", "confianza"):
        t.add_column(c)
    for k, v in lec.comprobante.model_dump(exclude={"items"}).items():
        conf = lec.confianza.get(k)
        t.add_row(k, "" if v is None else str(v), "" if conf is None else f"{conf:.2f}")
    consola.print(t)
    for o in obs:
        consola.print(f"  [yellow]{o.codigo}[/] ({o.origen}): {o.detalle}")
    color = "green" if dec.destino == "aprobado" else "yellow"
    consola.print(f"Destino: [{color}]{dec.destino}[/] {', '.join(dec.motivos)}")


def main() -> None:
    cargar_env()
    ap = argparse.ArgumentParser(prog="comprobantes", description="Lectura y validación de comprobantes de compra")
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("generar")
    p.add_argument("--escala", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=14)

    p = sub.add_parser("leer")
    p.add_argument("--demo", action="store_true", help="Tesseract y reglas, sin API key")
    p.add_argument("--n", type=int, help="Con LLM: tamaño de la muestra de octubre")
    p.add_argument("--modelo")
    p.add_argument("--procesos", type=int, default=2)

    p = sub.add_parser("evaluar")
    p.add_argument("--corrida", default="demo")

    p = sub.add_parser("resumen")
    p.add_argument("--corrida", default="demo")

    p = sub.add_parser("ver")
    p.add_argument("doc_id", type=int)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--modelo")

    sub.add_parser("todo")
    args = ap.parse_args()

    try:
        if args.comando == "todo":
            cmd_generar(argparse.Namespace(escala=1.0, seed=14))
            cmd_leer(argparse.Namespace(demo=True, n=None, modelo=None, procesos=2))
            cmd_evaluar(argparse.Namespace(corrida="demo"))
        else:
            {"generar": cmd_generar, "leer": cmd_leer, "evaluar": cmd_evaluar,
             "resumen": cmd_resumen, "ver": cmd_ver}[args.comando](args)
    except (RuntimeError, FileNotFoundError, duckdb.IOException, duckdb.CatalogException) as e:
        consola.print(f"[red]{e}[/]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
