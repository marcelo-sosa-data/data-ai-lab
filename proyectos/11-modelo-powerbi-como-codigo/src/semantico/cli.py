"""
Uso:
    python -m semantico generar [--escala 0.1]     # Parquet de origen de la Universidad Mirasol
    python -m semantico revisar                    # reglas sobre el TMDL (sale con 1 si hay errores)
    python -m semantico probar                     # medidas DAX contra el SQL de referencia
    python -m semantico probar --servicio <id>     # las mismas pruebas contra el modelo publicado
    python -m semantico errores                    # errores sembrados: cuáles atrapa el CI
    python -m semantico legado [--periodo 2026-2]  # las medidas de los reportes anteriores contra el modelo
    python -m semantico plan --base origin/main    # qué cambia y cuánto se mueven los números
    python -m semantico construir --ambiente test  # TMDL con los parámetros del ambiente
    python -m semantico publicar --ambiente test   # sube lo construido a Fabric con fabric-cicd
    python -m semantico refrescar --ambiente test --dataset <id>   # refresca y espera
    python -m semantico todo                       # generar si falta, revisar, probar, errores y legado
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import despliegue as D
from .dax import ErrorDAX
from .errores import evaluar_todos
from .legado import cargar_legado, comparar, revisar_legado
from .motor import Motor
from .pruebas import cargar_casos, conexion_sql, correr
from .reglas import hay_errores, revisar
from .tmdl import ErrorTMDL, cargar_modelo

RAIZ = Path(__file__).parents[2]
MODELO = RAIZ / "modelo" / D.NOMBRE_MODELO
DATOS = Path(os.getenv("SEMANTICO_DATOS", RAIZ / "datos" / "parquet"))
CASOS = RAIZ / "pruebas_dax" / "casos.yaml"
LEGADO = RAIZ / "legado"
AMBIENTES = RAIZ / "ambientes.yaml"
SALIDA = RAIZ / "salida"
RESULTADOS = RAIZ / "datos" / "resultados.json"
PERIODO_ACTUAL = "2026-2"

consola = Console()
CIAN = "#22D3EE"


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}", header_style="dim",
                 box=None, padding=(0, 2))


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.1%}" if abs(v) <= 1.5 else f"{v:,.2f}"
    return f"{v:,.0f}"


def _relativa(ruta: Path) -> Path:
    return ruta.relative_to(RAIZ) if ruta.is_relative_to(RAIZ) else ruta


def _hay_datos() -> bool:
    if not (DATOS / "matricula.parquet").exists():
        consola.print(f"[red]No hay datos en {DATOS}. Genéralos con: python -m semantico generar[/]")
        return False
    return True


def _guardar(clave: str, valor) -> None:
    previo = json.loads(RESULTADOS.read_text(encoding="utf-8")) if RESULTADOS.exists() else {}
    previo[clave] = valor
    RESULTADOS.parent.mkdir(parents=True, exist_ok=True)
    RESULTADOS.write_text(json.dumps(previo, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


# ------------------------------------------------------------------ comandos

def cmd_generar(args) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar
    t0 = time.time()
    generar(DATOS, escala=args.escala, seed=args.seed)
    consola.print(f"Parquet en {_relativa(DATOS)} "
                  f"({time.time() - t0:.1f} s)")
    return 0


def cmd_revisar(args) -> int:
    try:
        modelo = cargar_modelo(MODELO)
    except ErrorTMDL as e:
        consola.print(f"[red]El TMDL no se puede leer: {e}[/]")
        return 1
    hallazgos = revisar(modelo, {c.medida for c in cargar_casos(CASOS)})
    consola.print(f"{len(modelo.tablas)} tablas, {len(modelo.medidas)} medidas, "
                  f"{len(modelo.relaciones)} relaciones")
    if not hallazgos:
        consola.print("[green]Sin hallazgos[/]")
    else:
        t = _tabla("Hallazgos")
        for c in ("Regla", "Severidad", "Objeto", "Detalle"):
            t.add_column(c)
        for h in hallazgos:
            t.add_row(h.regla, f"[{'red' if h.severidad == 'error' else 'yellow'}]{h.severidad}[/]",
                      h.objeto, h.detalle)
        consola.print(t)
    _guardar("reglas", [asdict(h) for h in hallazgos])
    return 1 if hay_errores(hallazgos) else 0


def cmd_probar(args) -> int:
    casos = cargar_casos(CASOS)
    if args.servicio:
        return _probar_servicio(args.servicio, casos)
    if not _hay_datos():
        return 1
    modelo = cargar_modelo(MODELO)
    try:
        motor = Motor.desde_carpeta(modelo, DATOS)
    except ErrorDAX as e:
        consola.print(f"[red]{e}[/]")
        return 1
    t0 = time.time()
    resultados = correr(motor, casos, conexion_sql(DATOS))
    t = _tabla(f"Pruebas de medidas ({len(casos)} casos, {time.time() - t0:.1f} s)")
    for c in ("", "Caso", "Medida", "Grupos", "Detalle"):
        t.add_column(c)
    for r in resultados:
        detalle = r.error or "; ".join(f"{k}: esperado {_fmt(e)}, obtuvo {_fmt(o)}"
                                       for k, e, o in r.diferencias[:3])
        t.add_row("[green]ok[/]" if r.ok else "[red]falla[/]", r.caso.id, r.caso.medida,
                  str(len(r.esperado)), detalle)
    consola.print(t)
    fallas = sum(not r.ok for r in resultados)
    _guardar("pruebas", [{"id": r.caso.id, "medida": r.caso.medida, "ok": r.ok, "grupos": len(r.esperado),
                          "error": r.error, "diferencias": r.diferencias, "segundos": r.segundos}
                         for r in resultados])
    consola.print(f"{len(resultados) - fallas} de {len(resultados)} pasan")
    return 1 if fallas else 0


def _cliente_servicio(dataset_id: str):
    from azure.identity import ClientSecretCredential
    from .servicio import ClienteServicio

    cred = ClientSecretCredential(os.environ["AZURE_TENANT_ID"], os.environ["AZURE_CLIENT_ID"],
                                  os.environ["AZURE_CLIENT_SECRET"])
    token = cred.get_token("https://analysis.windows.net/powerbi/api/.default").token
    return ClienteServicio(dataset_id, token)


def _probar_servicio(dataset_id: str, casos) -> int:
    from .pruebas import comparar as comparar_valores

    if not _hay_datos():
        return 1
    cliente = _cliente_servicio(dataset_id)
    motor = Motor.desde_carpeta(cargar_modelo(MODELO), DATOS)
    fallas = 0
    for c in casos:
        difs = comparar_valores(motor.evaluar(c.medida, c.filtros, c.por), cliente.evaluar(c))
        fallas += bool(difs)
        consola.print(("[green]ok[/]  " if not difs else "[red]falla[/] ") + c.id)
    return 1 if fallas else 0


def cmd_errores(args) -> int:
    if not _hay_datos():
        return 1
    casos = cargar_casos(CASOS)
    t0 = time.time()
    with consola.status("Aplicando cada error y corriendo los controles..."):
        res = evaluar_todos(MODELO, DATOS, casos, conexion_sql(DATOS))
    t = _tabla(f"Errores sembrados ({time.time() - t0:.0f} s)")
    for c in ("Id", "Error", "Atrapado por", "Reglas", "Pruebas que fallan"):
        t.add_column(c)
    for r in res:
        quien = ", ".join(r.controles) if r.atrapado else f"[yellow]no bloquea[/] (avisos: {', '.join(r.avisos)})"
        t.add_row(r.error.id, r.error.descripcion, quien, ", ".join(r.reglas), str(len(r.pruebas_fallidas)))
    consola.print(t)
    atrapados = sum(r.atrapado for r in res)
    consola.print(f"{atrapados} de {len(res)} errores bloquean el merge")
    _guardar("errores", [{"id": r.error.id, "descripcion": r.error.descripcion, "atrapado": r.atrapado,
                          "controles": r.controles, "reglas": r.reglas, "avisos": r.avisos,
                          "pruebas_fallidas": r.pruebas_fallidas} for r in res])
    return 0


def cmd_legado(args) -> int:
    if not _hay_datos():
        return 1
    modelo = cargar_modelo(MODELO)
    motor = Motor.desde_carpeta(modelo, DATOS)
    legado = cargar_legado(LEGADO)
    filas = comparar(motor, legado, {"Periodo[periodo]": args.periodo})
    t = _tabla(f"Mismo indicador, distintos reportes ({args.periodo})")
    for c in ("Indicador", "Reporte", "Medida", "Valor"):
        t.add_column(c)
    for f in filas:
        estilo = f"[{CIAN}]" if f.reporte == "Modelo único" else ""
        t.add_row(f.indicador, f.reporte, f.medida, f"{estilo}{_fmt(f.valor)}")
    consola.print(t)
    hallazgos = revisar_legado(modelo, legado)
    t2 = _tabla("Reglas sobre las medidas de cada reporte")
    for c in ("Reporte", "Medidas", "Errores", "Reglas"):
        t2.add_column(c)
    for rep, hs in hallazgos.items():
        t2.add_row(rep, str(len(legado[rep])), str(sum(h.severidad == "error" for h in hs)),
                   ", ".join(sorted({h.regla for h in hs})))
    consola.print(t2)
    _guardar("legado", {"periodo": args.periodo, "comparacion": [asdict(f) for f in filas],
                        "reglas": {r: [asdict(h) for h in hs] for r, hs in hallazgos.items()},
                        "medidas": {r: len(m) for r, m in legado.items()}})
    return 0


def cmd_plan(args) -> int:
    try:
        base = D.modelo_en_git(args.base, MODELO, RAIZ)
    except Exception as e:  # noqa: BLE001 - git falla de varias formas y todas se reportan igual
        consola.print(f"[red]No pude leer el modelo en {args.base}: {e}[/]")
        return 1
    nuevo = cargar_modelo(MODELO)
    datos = DATOS if (DATOS / "matricula.parquet").exists() else None
    p = D.plan(base, nuevo, datos, {"Periodo[periodo]": args.periodo})
    md = D.plan_markdown(p, f"Cambios en el modelo frente a {args.base}")
    if args.salida:
        Path(args.salida).write_text(md, encoding="utf-8")
    consola.print(md)
    return 0


def cmd_construir(args) -> int:
    destino = D.construir(MODELO, args.ambiente, D.cargar_ambientes(AMBIENTES), SALIDA)
    consola.print(f"Modelo para {args.ambiente} en {_relativa(destino)}")
    return 0


def cmd_publicar(args) -> int:
    ambientes = D.cargar_ambientes(AMBIENTES)
    destino = SALIDA / args.ambiente / D.NOMBRE_MODELO
    if not destino.exists():
        destino = D.construir(MODELO, args.ambiente, ambientes, SALIDA)
    try:
        r = D.publicar(destino, args.ambiente, ambientes)
    except RuntimeError as e:
        consola.print(f"[red]{e}[/]")
        return 1
    consola.print(f"Publicado en {r['workspace']}")
    return 0


def cmd_refrescar(args) -> int:
    ambientes = D.cargar_ambientes(AMBIENTES)
    workspace = os.environ[ambientes[args.ambiente]["variable_workspace_id"]]
    try:
        estado = _cliente_servicio(args.dataset).refrescar(workspace)
    except RuntimeError as e:
        consola.print(f"[red]{e}[/]")
        return 1
    consola.print(f"Refresco {estado}")
    return 0


def cmd_todo(args) -> int:
    if not (DATOS / "matricula.parquet").exists():
        cmd_generar(argparse.Namespace(escala=1.0, seed=11))
    codigos = [cmd_revisar(args), cmd_probar(argparse.Namespace(servicio=None)), cmd_errores(args),
               cmd_legado(argparse.Namespace(periodo=PERIODO_ACTUAL))]
    return max(codigos)


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ruta)
    except ImportError:
        pass


def main(argv=None) -> int:
    cargar_env()
    p = argparse.ArgumentParser(prog="semantico", description="Modelo semántico de matrícula como código")
    sub = p.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--escala", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=11)
    sub.add_parser("revisar")
    pr = sub.add_parser("probar")
    pr.add_argument("--servicio", metavar="DATASET_ID", help="Prueba contra el modelo publicado")
    sub.add_parser("errores")
    lg = sub.add_parser("legado")
    lg.add_argument("--periodo", default=PERIODO_ACTUAL)
    pl = sub.add_parser("plan")
    pl.add_argument("--base", default="origin/main")
    pl.add_argument("--periodo", default=PERIODO_ACTUAL)
    pl.add_argument("--salida", help="Escribe el plan en Markdown en este archivo")
    for nombre in ("construir", "publicar"):
        c = sub.add_parser(nombre)
        c.add_argument("--ambiente", required=True, choices=["dev", "test", "prod"])
    rf = sub.add_parser("refrescar")
    rf.add_argument("--ambiente", required=True, choices=["dev", "test", "prod"])
    rf.add_argument("--dataset", required=True, metavar="DATASET_ID")
    sub.add_parser("todo")
    args = p.parse_args(argv)
    return globals()[f"cmd_{args.comando}"](args)
