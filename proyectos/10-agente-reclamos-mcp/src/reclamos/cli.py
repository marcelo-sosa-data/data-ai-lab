"""
Uso:
    python -m reclamos generar [--escala 0.1]
    python -m reclamos atender 1 --demo --detalle
    python -m reclamos evaluar --demo               # todos los reclamos con el flujo fijo
    python -m reclamos evaluar --n 40               # muestra con el LLM configurado en .env
    python -m reclamos juez                         # calibración del juez de reglas (y del LLM si hay clave)
    python -m reclamos resumen
    python -m reclamos servidor                     # servidor MCP por stdio
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
from rich.console import Console
from rich.table import Table

from . import evaluacion as ev
from .rutas import RAIZ, ruta_db, ruta_resultados

consola = Console()


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ruta)
    except ImportError:
        pass


def crear_agente(demo: bool, db: Path | None = None, modelo: str | None = None):
    from .agente import AgenteReclamos
    from .llm import ModeloDemo, ModeloLLM
    from .servidor import Sistemas

    return AgenteReclamos(ModeloDemo() if demo else ModeloLLM(modelo), Sistemas(db or ruta_db()))


def _nombre_corrida(demo: bool) -> str:
    if demo:
        return "demo"
    modelo = os.getenv("LLM_MODELO", "llm")
    return "llm_" + "".join(c if c.isalnum() else "_" for c in modelo.lower())


def _guardar_resumen(con, corrida: str, datos: dict) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS resumen (corrida VARCHAR PRIMARY KEY, datos JSON)")
    con.execute("INSERT OR REPLACE INTO resumen VALUES (?, ?)", [corrida, json.dumps(datos, ensure_ascii=False)])


# ------------------------------------------------------------------ comandos

def cmd_generar(a) -> None:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar

    ruta = generar(ruta_db(), a.escala, a.seed)
    consola.print(f"Base en {ruta}")


def cmd_atender(a) -> None:
    agente = crear_agente(a.demo)
    res = agente.atender(a.id_reclamo)
    if a.detalle:
        for i, p in enumerate(res.pasos, 1):
            color = "red" if p.error else "cyan"
            consola.print(f"[{color}]{i:02d} {p.herramienta}[/] {json.dumps(p.entrada, ensure_ascii=False)[:160]}")
            consola.print(f"   [dim]{p.salida[:300]}[/]")
    consola.print(f"[bold]{res.codigo}[/] perfil={res.perfil} acción={res.accion} "
                  f"abono=S/ {res.monto_abonado:.2f} pasos={len(res.pasos)} denegadas={res.denegadas}")
    consola.print(res.mensaje)


def cmd_evaluar(a) -> None:
    con = duckdb.connect(str(ruta_db()), read_only=True)
    verdad = ev.cargar_verdad(con)
    as_is = ev.indicadores_as_is(con)
    con.close()
    ids = verdad.id_reclamo.tolist() if a.demo and not a.n else ev.muestra(verdad, a.n or 40, a.seed)
    agente = crear_agente(a.demo)
    corrida = _nombre_corrida(a.demo)
    consola.print(f"Atendiendo {len(ids)} reclamos con {agente.modelo.nombre}...")

    def avance(i, r):
        if not a.demo or i % 500 == 0:
            consola.print(f"  {i}/{len(ids)} {r.codigo} {r.accion} ({r.segundos:.0f} s)")

    resultados = agente.atender_lote(ids, avance)
    t = ev.tabla_resultados(resultados, verdad)
    to_be = ev.indicadores_to_be(t)
    to_be["acierto_ic"] = ev.intervalo(t.acierto)
    to_be["macro_bien_derivados_muestra"] = ev.macro_sobre_muestra(t)
    to_be["modelo"] = agente.modelo.nombre
    to_be["tokens_promedio"] = float(t.tokens.mean())
    to_be["segundos_promedio"] = float(t.segundos.mean())

    out = duckdb.connect(str(ruta_resultados()))
    out.register("t", t.drop(columns=["texto"]))
    out.execute(f"CREATE OR REPLACE TABLE to_be_{corrida} AS SELECT * FROM t")
    out.register("p", ev.acierto_por_tipo(t))
    out.execute(f"CREATE OR REPLACE TABLE por_tipo_{corrida} AS SELECT * FROM p")
    con = duckdb.connect(str(ruta_db()), read_only=True)
    out.register("m", ev.mensual_as_is(con))
    out.register("r", ev.regla_actual_por_tipo(con))
    con.close()
    out.execute("CREATE OR REPLACE TABLE mensual_as_is AS SELECT * FROM m")
    out.execute("CREATE OR REPLACE TABLE macro_por_tipo AS SELECT * FROM r")
    _guardar_resumen(out, "as_is", as_is)
    _guardar_resumen(out, corrida, to_be)
    out.close()
    mostrar_comparacion(as_is, to_be)
    tabla = Table("tipo", "caso", "reclamos", "acierto", header_style="bold")
    for f in ev.acierto_por_tipo(t).itertuples():
        tabla.add_row(f.tipo, f.caso, str(f.reclamos), f"{f.acierto:.1%}")
    consola.print(tabla)


def mostrar_comparacion(as_is: dict, to_be: dict) -> None:
    t = Table("Indicador", "AS IS", f"TO BE ({to_be['modelo']})", header_style="bold")
    lo, hi = to_be["acierto_ic"]
    t.add_row("Bien encaminados a la primera", f"{as_is['bien_derivados_primera']:.1%} (macro)",
              f"{to_be['acierto']:.1%} [{lo:.1%}, {hi:.1%}]")
    t.add_row("Cerrados en el primer contacto", f"{as_is['cerrados_en_primer_contacto']:.0%}",
              f"{to_be['cerrados_en_primer_contacto']:.1%}")
    t.add_row("Abonos indebidos", f"{as_is['abonos_indebidos_n']} (S/ {as_is['abonos_indebidos_soles']:,.0f})",
              f"{to_be['abonos_indebidos_n']} (S/ {to_be['abonos_indebidos_soles']:,.0f})")
    t.add_row("Abonos que procedían y no se hicieron", str(as_is["abonos_que_procedian_no_hechos"]),
              str(to_be["abonos_que_procedian_no_hechos"]))
    t.add_row("Bloqueos de tarjeta innecesarios", str(as_is["bloqueos_innecesarios"]),
              str(to_be["bloqueos_innecesarios"]))
    t.add_row("Reclamos evaluados", f"{as_is['reclamos']:,}", f"{to_be['reclamos']:,}")
    consola.print(t)
    consola.print(f"[dim]AS IS: mediana {as_is['mediana_dias_habiles']:.0f} días hábiles, "
                  f"{as_is['fuera_de_plazo']:.1%} fuera de plazo, {as_is['rederivados']:.1%} rederivados. "
                  f"TO BE: {to_be['inyecciones_con_abono']} abonos en {to_be['inyecciones']} reclamos con "
                  f"inyección, {to_be['pii_al_modelo']} datos personales enviados al modelo, "
                  f"{to_be['llamadas_denegadas']} llamadas denegadas, {to_be['cerrados_por_host']} cerrados por el host.[/]")


def cmd_juez(a) -> None:
    from . import juez as jz
    from .set_juez import armar

    # se lee todo al inicio y se escribe al final: el juez con LLM puede tardar y el tablero sigue leyendo
    out = duckdb.connect(str(ruta_resultados()), read_only=True)
    tablas = {r[0] for r in out.execute("SHOW TABLES").fetchall()}
    if "to_be_demo" not in tablas:
        out.close()
        consola.print("Primero corre: python -m reclamos evaluar --demo")
        return
    base = out.execute("SELECT * FROM to_be_demo").df()
    mensajes_llm = {t: out.execute(f"SELECT mensaje, accion, monto_abonado FROM {t} WHERE mensaje <> ''").df()
                    for t in sorted(t for t in tablas if t.startswith("to_be_llm"))}
    previo = out.execute("SELECT * FROM set_juez").df() if a.reusar and "set_juez" in tablas else None
    previas = {}
    if a.reusar and "resumen" in tablas:
        fila = out.execute("SELECT datos FROM resumen WHERE corrida = 'juez'").fetchone()
        previas = json.loads(fila[0]) if fila else {}
    out.close()
    sj = armar(base, a.n, seed=a.seed)
    if previo is not None and previo.mensaje.tolist() != sj.mensaje.tolist():
        previo, previas = None, {}  # el set cambió: no hay nada que reusar
    jueces = [jz.JuezReglas()]
    if not a.solo_reglas and os.getenv("LLM_API_KEY"):
        jueces.append(jz.JuezLLM())
    metricas = {}
    for juez in jueces:
        col = f"juez_{juez.nombre}"
        if previo is not None and col in previo:
            # --reusar: el set no cambió, se toman los veredictos ya calculados
            sj[col], sj[col + "_falla"] = previo[col].values, previo[col + "_falla"].values
        else:
            veredictos = []
            for i, f in enumerate(sj.itertuples(), 1):
                veredictos.append(juez.evaluar(f.mensaje, f.accion, f.monto_abonado))
                if isinstance(juez, jz.JuezLLM) and i % 20 == 0:
                    consola.print(f"  {juez.nombre}: {i}/{len(sj)}")
            sj[col] = [v.aprueba for v in veredictos]
            sj[col + "_falla"] = [",".join(v.falla) for v in veredictos]
        m = jz.matriz(sj.etiqueta, sj[col])
        m["recall_por_defecto"] = jz.recall_por_defecto(sj, col).to_dict("records")
        m["validacion_correccion"] = jz.validar_correccion(sj, col)
        # aplicado a los mensajes de las corridas con LLM, que no tienen etiqueta
        objetivos = {}
        for tabla, msgs in mensajes_llm.items():
            if len(msgs):
                aprob = pd.Series([juez.evaluar(r.mensaje, r.accion, r.monto_abonado).aprueba
                                   for r in msgs.itertuples()])
                objetivos[tabla] = jz.corregir_con_intervalo(sj.rename(columns={col: "juez"}), aprob)
        m["objetivos"] = objetivos
        metricas[juez.nombre] = m
        consola.print(f"[bold]{juez.nombre}[/] n={m['n']} sensibilidad={m['sensibilidad']:.1%} "
                      f"especificidad={m['especificidad']:.1%} kappa={m['kappa']:.2f}")
        vc = m["validacion_correccion"]
        consola.print(f"   tasa de aprobación en media muestra: error {vc['error_observada']:.1%} sin corregir, "
                      f"{vc['error_corregida']:.1%} corregida ({vc['repeticiones']} particiones)")
        for d in m["recall_por_defecto"]:
            consola.print(f"   {d['defecto']:<14} {d['mensajes']:>3} detectados {d['detectados']:.0%}")
        for tabla, o in objetivos.items():
            consola.print(f"   {tabla}: aprueba {o['observada']:.1%}, corregida {o['corregida']:.1%} "
                          f"[{o['ic_bajo']:.1%}, {o['ic_alto']:.1%}]")
    # --reusar conserva los jueces que no se corrieron esta vez (por ejemplo, el LLM sin clave a mano)
    if previo is not None:
        for nombre, m in previas.items():
            col = f"juez_{nombre}"
            if nombre not in metricas and col in previo:
                sj[col], sj[col + "_falla"] = previo[col].values, previo[col + "_falla"].values
                metricas[nombre] = m
    out = duckdb.connect(str(ruta_resultados()))
    out.register("sj", sj)
    out.execute("CREATE OR REPLACE TABLE set_juez AS SELECT * FROM sj")
    _guardar_resumen(out, "juez", metricas)
    out.close()


def cmd_resumen(a) -> None:
    out = duckdb.connect(str(ruta_resultados()), read_only=True)
    filas = dict(out.execute("SELECT corrida, datos FROM resumen").fetchall())
    out.close()
    as_is = json.loads(filas["as_is"])
    for corrida, datos in filas.items():
        if corrida.startswith(("demo", "llm")):
            mostrar_comparacion(as_is, json.loads(datos))


def cmd_servidor(a) -> None:
    from .servidor import Sistemas, crear_servidor

    crear_servidor(Sistemas(ruta_db())).run("stdio")


def main(argv: list[str] | None = None) -> int:
    cargar_env()
    p = argparse.ArgumentParser(prog="reclamos", description="Agente de reclamos de Killa con MCP")
    sub = p.add_subparsers(dest="comando", required=True)

    g = sub.add_parser("generar", help="genera la base sintética")
    g.add_argument("--escala", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=2026)
    g.set_defaults(fn=cmd_generar)

    at = sub.add_parser("atender", help="atiende un reclamo")
    at.add_argument("id_reclamo", type=int)
    at.add_argument("--demo", action="store_true")
    at.add_argument("--detalle", action="store_true")
    at.set_defaults(fn=cmd_atender)

    e = sub.add_parser("evaluar", help="corre el agente sobre los reclamos y compara con el AS IS")
    e.add_argument("--demo", action="store_true")
    e.add_argument("--n", type=int, default=0, help="tamaño de la muestra (con LLM, 40 por defecto)")
    e.add_argument("--seed", type=int, default=11)
    e.set_defaults(fn=cmd_evaluar)

    j = sub.add_parser("juez", help="calibra el juez contra el set etiquetado")
    j.add_argument("--n", type=int, default=160)
    j.add_argument("--seed", type=int, default=21)
    j.add_argument("--solo-reglas", action="store_true")
    j.add_argument("--reusar", action="store_true", help="reusa los veredictos del set si no cambió")
    j.set_defaults(fn=cmd_juez)

    sub.add_parser("resumen", help="vuelve a mostrar la comparación").set_defaults(fn=cmd_resumen)
    sub.add_parser("servidor", help="servidor MCP por stdio").set_defaults(fn=cmd_servidor)

    a = p.parse_args(argv)
    a.fn(a)
    return 0
