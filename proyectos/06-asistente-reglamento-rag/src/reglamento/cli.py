"""
Uso:
    python -m reglamento generar                      # corpus y preguntas sintéticas
    python -m reglamento corpus                       # documentos, artículos y modificaciones
    python -m reglamento preguntar "hasta cuando me puedo retirar de un curso?" --demo
    python -m reglamento preguntar "..." --fecha 2025-10-01 --detalle
    python -m reglamento evaluar                      # búsqueda, umbral y respuestas extractivas
    python -m reglamento evaluar --modelos            # compara tres modelos de vectores (descarga ~3.5 GB)
    python -m reglamento todo                         # generar + evaluar
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .asistente import Asistente, Respuesta
from .corpus import Fragmento, cargar_corpus
from .embeddings import MODELO_DEFECTO, MODELOS_COMPARADOS, CodificadorLocal
from .evaluacion import (FECHA_EVALUACION, calibrar_umbral, cargar_preguntas, evaluar_abstencion,
                         evaluar_busqueda, evaluar_respuestas, resumen_busqueda, resumen_respuestas,
                         separacion)
from .llm import ModeloExtractivo, ModeloLLM
from .recuperador import CONFIGURACIONES, DEFECTO, SIN_VECTORES, Configuracion, Recuperador
from .rutas import RAIZ, ruta_corpus, ruta_datos, ruta_preguntas, ruta_resultados, ruta_vectores

consola = Console()
CIAN, VERDE, ROJO, AMBAR, GRIS = "#22D3EE", "#34D399", "#F87171", "#FBBF24", "#7D8B99"


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ruta)
    except ImportError:
        pass


def crear_recuperador(sin_vectores: bool = False, modelo: str | None = None) -> tuple[Recuperador, Configuracion]:
    fragmentos = cargar_corpus(ruta_corpus())
    if sin_vectores:
        return Recuperador(fragmentos), SIN_VECTORES
    codificador = CodificadorLocal(modelo)
    return Recuperador(fragmentos, codificador, ruta_vectores(codificador.nombre)), DEFECTO


def leer_umbral(config: Configuracion, modelo: str | None) -> float:
    """Umbral calibrado por `evaluar` para esta configuración; 0 si no hay (no se abstiene por confianza)."""
    ruta = ruta_resultados() / "resumen.json"
    if not ruta.exists():
        return 0.0
    umbrales = json.loads(ruta.read_text(encoding="utf-8")).get("umbrales", {})
    clave = config.nombre if not config.vectorial else f"{config.nombre} · {modelo}"
    return float(umbrales.get(clave, {}).get("umbral", 0.0))


def crear_asistente(demo: bool, sin_vectores: bool = False, modelo_llm: str | None = None) -> Asistente:
    recuperador, config = crear_recuperador(sin_vectores)
    nombre_vec = recuperador.codificador.nombre if recuperador.codificador else None
    llm = ModeloExtractivo() if demo else ModeloLLM(modelo_llm)
    return Asistente(recuperador, llm, leer_umbral(config, nombre_vec), config=config)


# ----------------------------------------------------------------- comandos

def cmd_generar(args) -> None:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_corpus import generar

    rutas = generar(ruta_datos(), args.seed)
    preguntas = cargar_preguntas(rutas["preguntas"])
    fragmentos = cargar_corpus(rutas["corpus"])
    consola.print(f"[{VERDE}]✓[/] {len(list(rutas['corpus'].glob('*.md')))} documentos · "
                  f"{len(fragmentos)} fragmentos · {len(preguntas)} preguntas")


def cmd_corpus(args) -> None:
    fragmentos = cargar_corpus(ruta_corpus())
    t = Table(title="Corpus", title_justify="left", title_style=f"bold {CIAN}", header_style="dim", box=None)
    for c in ("documento", "artículos", "modificados", "incorporados"):
        t.add_column(c)
    por_doc: dict[str, list[Fragmento]] = {}
    for f in fragmentos:
        por_doc.setdefault(f.documento, []).append(f)
    for doc, fs in por_doc.items():
        mods = [f for f in fs if f.fuente != doc]
        originales = {f.articulo for f in fs if f.fuente == doc}
        t.add_row(f"{doc} · {fs[0].titulo_documento}", str(len(originales)),
                  ", ".join(f.articulo for f in mods if f.articulo in originales) or "-",
                  ", ".join(f.articulo for f in mods if f.articulo not in originales) or "-")
    consola.print(t)
    for f in fragmentos:
        if f.vigente_hasta:
            consola.print(f"[dim]{f.id} vigente hasta {f.vigente_hasta:%d/%m/%Y}[/]")


def mostrar(r: Respuesta, detalle: bool) -> None:
    if detalle:
        t = Table(title=f"Búsqueda · fecha {r.fecha:%d/%m/%Y}", title_justify="left",
                  title_style=f"bold {CIAN}", header_style="dim", box=None, padding=(0, 2))
        for c in ("#", "artículo", "título", "coseno", "bm25"):
            t.add_column(c, justify="right" if c in ("#", "coseno", "bm25") else "left")
        for i, res in enumerate(r.busqueda.resultados, 1):
            citado = res.fragmento in r.citas
            t.add_row(str(i), f"[{VERDE if citado else 'white'}]{res.fragmento.cita}[/]", res.fragmento.titulo,
                      "-" if res.coseno is None else f"{res.coseno:.3f}", f"{res.bm25:.2f}")
        consola.print(t)
        consola.print(f"[dim]confianza {r.busqueda.confianza:.3f}[/]")
    color = VERDE if r.respondio else AMBAR
    titulo = "Respuesta" if r.respondio else f"Sin respuesta ({r.abstencion})"
    consola.print(Panel(r.texto, title=titulo, title_align="left", border_style=color))
    if r.citas:
        consola.print("[dim]Fuentes:[/] " + " · ".join(f"[{CIAN}]{f.cita}[/]" for f in r.citas))
    consola.print(f"[dim]{r.segundos:.2f} s · {r.tokens_entrada + r.tokens_salida:,} tokens[/]")


def cmd_preguntar(args) -> None:
    try:
        asistente = crear_asistente(args.demo, args.sin_vectores, args.modelo)
    except (RuntimeError, FileNotFoundError) as e:
        consola.print(f"[{ROJO}]{e}[/]")
        raise SystemExit(1)
    fecha = date.fromisoformat(args.fecha) if args.fecha else date.today()
    consola.print(f"[dim]modelo: {asistente.modelo.nombre} · búsqueda: {asistente.config.nombre} · "
                  f"umbral {asistente.umbral:.3f}[/]")
    mostrar(asistente.preguntar(args.pregunta, fecha), args.detalle)


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def cmd_evaluar(args) -> None:
    inicio = time.perf_counter()
    preguntas = cargar_preguntas(ruta_preguntas())
    salida = ruta_resultados()
    salida.mkdir(parents=True, exist_ok=True)
    fragmentos = cargar_corpus(ruta_corpus())

    # 1. búsqueda: todas las configuraciones con el modelo por defecto
    recuperador = Recuperador(fragmentos)
    try:
        cod = CodificadorLocal(MODELO_DEFECTO)
        recuperador = Recuperador(fragmentos, cod, ruta_vectores(cod.nombre))
    except Exception as e:  # sin red o sin fastembed: se evalúa solo lo léxico
        consola.print(f"[{AMBAR}]Sin modelo de vectores ({e}). Solo se evalúa BM25.[/]")
    configs = [c for c in CONFIGURACIONES.values() if recuperador.codificador or not c.vectorial]
    detalle = pd.concat([evaluar_busqueda(recuperador, preguntas, c) for c in configs], ignore_index=True)
    detalle.to_csv(salida / "busqueda.csv", index=False)

    tabla = resumen_busqueda(detalle, ["config", "split"])
    por_registro = resumen_busqueda(detalle[detalle["split"] == "prueba"], ["config", "registro"])
    versiones = (detalle[detalle["tipo"] == "vigencia"].groupby("config", sort=False)["error_version"]
                 .agg(["sum", "size"]).reset_index())

    # 2. umbral de abstención: se calibra en desarrollo, se mide en prueba
    umbrales = {}
    for c in configs:
        d = detalle[detalle["config"] == c.nombre]
        u = calibrar_umbral(d[d["split"] == "desarrollo"])
        clave = c.nombre if not c.vectorial else f"{c.nombre} · {recuperador.codificador.nombre}"
        umbrales[clave] = {**evaluar_abstencion(d[d["split"] == "prueba"], u),
                           "auc": round(separacion(d[d["split"] == "prueba"]), 3)}

    # 3. respuestas en modo extractivo (las de prueba), con la configuración por defecto
    config = DEFECTO if recuperador.codificador else SIN_VECTORES
    clave = config.nombre if not config.vectorial else f"{config.nombre} · {recuperador.codificador.nombre}"
    asistente = Asistente(recuperador, ModeloExtractivo(), umbrales[clave]["umbral"], config=config)
    prueba = [q for q in preguntas if q["split"] == "prueba"]
    respuestas = evaluar_respuestas(asistente, prueba)
    respuestas.to_csv(salida / "respuestas_extractivo.csv", index=False)

    resumen = {
        "fecha_evaluacion": FECHA_EVALUACION.isoformat(),
        "preguntas": len(preguntas),
        "modelo_vectores": recuperador.codificador.nombre if recuperador.codificador else None,
        "busqueda": tabla.round(4).to_dict(orient="records"),
        "busqueda_por_registro": por_registro.round(4).to_dict(orient="records"),
        "errores_version": versiones.rename(columns={"sum": "errores", "size": "n"}).to_dict(orient="records"),
        "umbrales": umbrales,
        "respuestas_extractivo": {"config": clave, **resumen_respuestas(respuestas)},
    }

    # 4. opcional: comparar modelos de vectores (solo búsqueda vectorial)
    if args.modelos:
        filas = []
        for m in MODELOS_COMPARADOS:
            cod = CodificadorLocal(m)
            rec = Recuperador(fragmentos, cod, ruta_vectores(m))
            t0 = time.perf_counter()
            d = evaluar_busqueda(rec, preguntas, CONFIGURACIONES["vectorial"])
            seg = time.perf_counter() - t0
            r = resumen_busqueda(d[d["split"] == "prueba"], ["registro"])
            fila = {"modelo": m, "auc": round(separacion(d[d["split"] == "prueba"]), 3),
                    "ms_por_pregunta": round(1000 * seg / len(preguntas), 1)}
            for _, x in r.iterrows():
                fila[f"acierto@1 {x['registro']}"] = round(x["acierto@1"], 4)
                fila[f"acierto@5 {x['registro']}"] = round(x["acierto@5"], 4)
            filas.append(fila)
        resumen["modelos"] = filas

    (salida / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    _imprimir_resumen(resumen)
    consola.print(f"[dim]{time.perf_counter() - inicio:.0f} s · resultados en {salida}[/]")


def _imprimir_resumen(r: dict) -> None:
    t = Table(title=f"Búsqueda · preguntas de prueba con respuesta · fecha {r['fecha_evaluacion']}",
              title_justify="left", title_style=f"bold {CIAN}", header_style="dim", box=None, padding=(0, 2))
    for c in ("configuración", "acierto@1 formal", "acierto@1 coloquial", "acierto@5", "mrr"):
        t.add_column(c, justify="left" if c == "configuración" else "right")
    reg = pd.DataFrame(r["busqueda_por_registro"])
    tot = pd.DataFrame(r["busqueda"])
    tot = tot[tot["split"] == "prueba"].set_index("config")
    for cfg in tot.index:
        f = reg[(reg["config"] == cfg) & (reg["registro"] == "formal")].iloc[0]
        c = reg[(reg["config"] == cfg) & (reg["registro"] == "coloquial")].iloc[0]
        t.add_row(cfg, _pct(f["acierto@1"]), _pct(c["acierto@1"]), _pct(tot.loc[cfg, "acierto@5"]),
                  f"{tot.loc[cfg, 'mrr']:.3f}")
    consola.print(t)

    for e in r["errores_version"]:
        color = ROJO if e["errores"] else VERDE
        consola.print(f"  versión derogada antes que la vigente · {e['config']}: [{color}]{e['errores']}/{e['n']}[/]")

    clave = r["respuestas_extractivo"]["config"]
    u = r["umbrales"][clave]
    consola.print(f"\n[bold {CIAN}]Abstención[/] · {clave} · umbral {u['umbral']:.3f} (desarrollo) · AUC {u['auc']}")
    consola.print(f"  con respuesta que responde: {u['validas_respondidas']}/{u['validas']}   "
                  f"sin respuesta que se abstiene: {u['sin_respuesta_abstenidas']}/{u['sin_respuesta']}")
    x = r["respuestas_extractivo"]
    consola.print(f"\n[bold {CIAN}]Modo extractivo[/] · cita correcta {x['cita_correcta']}/{x['validas']} · "
                  f"dato esperado en el texto {x['dato_en_texto']}/{x['validas']}")
    if "modelos" in r:
        t = Table(title="Modelos de vectores (vectorial, prueba)", title_justify="left",
                  title_style=f"bold {CIAN}", header_style="dim", box=None, padding=(0, 2))
        for c in ("modelo", "acierto@1 formal", "acierto@1 coloquial", "AUC", "ms/pregunta"):
            t.add_column(c, justify="left" if c == "modelo" else "right")
        for m in r["modelos"]:
            t.add_row(m["modelo"].split("/")[-1].replace("paraphrase-multilingual-", ""), _pct(m["acierto@1 formal"]), _pct(m["acierto@1 coloquial"]),
                      str(m["auc"]), str(m["ms_por_pregunta"]))
        consola.print(t)


def main(argv: list[str] | None = None) -> None:
    cargar_env()
    parser = argparse.ArgumentParser(prog="reglamento", description="Asistente del reglamento académico.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("generar", help="corpus y preguntas sintéticas")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(fn=cmd_generar)

    sub.add_parser("corpus", help="documentos y modificaciones").set_defaults(fn=cmd_corpus)

    p = sub.add_parser("preguntar", help="responde una pregunta con citas")
    p.add_argument("pregunta")
    p.add_argument("--fecha", help="fecha de la consulta (YYYY-MM-DD); por defecto hoy")
    p.add_argument("--demo", action="store_true", help="sin API key: respuesta extractiva")
    p.add_argument("--sin-vectores", action="store_true", help="solo BM25 con sinónimos, sin descargar modelos")
    p.add_argument("--modelo", help="modelo LLM (por defecto LLM_MODELO)")
    p.add_argument("--detalle", action="store_true", help="muestra los artículos recuperados")
    p.set_defaults(fn=cmd_preguntar)

    p = sub.add_parser("evaluar", help="búsqueda, umbral y respuestas extractivas")
    p.add_argument("--modelos", action="store_true", help="compara tres modelos de vectores")
    p.set_defaults(fn=cmd_evaluar)

    p = sub.add_parser("todo", help="generar y evaluar")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--modelos", action="store_true")
    p.set_defaults(fn=lambda a: (cmd_generar(a), cmd_evaluar(a)))

    args = parser.parse_args(argv)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    args.fn(args)


if __name__ == "__main__":
    main()
