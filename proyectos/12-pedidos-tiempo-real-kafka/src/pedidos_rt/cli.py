"""Línea de comandos.

    python -m pedidos_rt generar            # semana de eventos sintéticos
    python -m pedidos_rt publicar           # repite los eventos contra el broker
    python -m pedidos_rt procesar           # corre el procesador hasta Ctrl+C
    python -m pedidos_rt evaluar            # tablero actual vs streaming, resultados.duckdb
    python -m pedidos_rt todo               # generar + publicar + evaluar
    python -m pedidos_rt en-vivo            # publica a 60x y procesa a la vez, para el tablero
    python -m pedidos_rt resumen            # vuelve a mostrar la comparación
"""

from __future__ import annotations

import argparse
import shutil
import sys
import threading
import time
from dataclasses import replace

import duckdb
from rich.console import Console
from rich.table import Table

from .config import DIR_DATOS, RAIZ, Ajustes

consola = Console()


def _generador():
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar  # noqa: E402
    return generar


def cmd_generar(a, aj):
    t = time.time()
    ruta = _generador()(DIR_DATOS, escala=a.escala, seed=a.seed)
    n = duckdb.connect().execute(f"SELECT count(*) FROM '{ruta.as_posix()}'").fetchone()[0]
    consola.print(f"{n:,} eventos en {ruta.name} ({time.time() - t:.1f} s)")


def cmd_publicar(a, aj):
    from .productor import preparar_topicos, publicar
    preparar_topicos(aj, reiniciar=a.reiniciar)
    t = time.time()
    n = publicar(aj, DIR_DATOS / "eventos.parquet", velocidad=a.velocidad)
    consola.print(f"{n:,} mensajes en {aj.topicos.eventos} ({time.time() - t:.1f} s)")


def cmd_procesar(a, aj):
    from .procesador import correr
    salida = aj.dir_salida / a.carpeta
    tardios = correr(replace(aj, gracia_ms=a.gracia * 1000), a.grupo, salida,
                     espera_s=a.espera)
    consola.print(f"Listo. {tardios:,} eventos fuera de la gracia quedaron en {salida / 'tardios'}")


def cmd_evaluar(a, aj):
    from .evaluacion import evaluar
    t = time.time()
    evaluar(aj, DIR_DATOS, procesar=not a.sin_procesar)
    consola.print(f"resultados.duckdb actualizado ({time.time() - t:.0f} s)")
    cmd_resumen(a, aj)


def cmd_todo(a, aj):
    a.reiniciar, a.velocidad, a.sin_procesar = True, 0.0, False
    cmd_generar(a, aj)
    cmd_publicar(a, aj)
    cmd_evaluar(a, aj)


def cmd_en_vivo(a, aj):
    from .procesador import correr
    from .productor import preparar_topicos, publicar
    preparar_topicos(aj, reiniciar=True)
    salida = aj.dir_salida / "en_vivo"
    shutil.rmtree(salida, ignore_errors=True)
    shutil.rmtree(aj.dir_estado / "en-vivo", ignore_errors=True)
    hilo = threading.Thread(target=publicar, daemon=True,
                            args=(aj, DIR_DATOS / "eventos.parquet", a.velocidad))
    hilo.start()
    consola.print(f"Publicando a {a.velocidad:g}x. Abre el tablero en otra terminal. Ctrl+C para parar.")
    correr(aj, "en-vivo", salida, publicar=True)


def cmd_resumen(a, aj):
    ruta = DIR_DATOS / "resultados.duckdb"
    if not ruta.exists():
        consola.print("No hay resultados. Corre: python -m pedidos_rt todo")
        return
    with duckdb.connect(str(ruta), read_only=True) as con:
        df = con.execute("SELECT * FROM resumen").df()
        fl = con.execute("SELECT * FROM consistencia_flujo ORDER BY gracia_s").df()
    t = Table(title="Detección de saturación por zona")
    for c in ("Variante", "Detectados", "Mediana (min)", "Falsas", "Pedidos antes de la alerta"):
        t.add_column(c, justify="left" if c == "Variante" else "right")
    for f in df.itertuples():
        t.add_row(f.variante, f"{f.detectados}/{f.incidentes}", f"{f.demora_mediana_min}",
                  f"{f.falsas_alarmas}", f"{f.pedidos_antes_alerta:,}")
    consola.print(t)
    t = Table(title="Métricas por minuto según la gracia")
    for c in ("Gracia (s)", "Retraso mediano (s)", "Asignaciones fuera de su minuto"):
        t.add_column(c, justify="right")
    for f in fl.itertuples():
        t.add_row(f"{int(f.gracia_s)}", f"{f.retraso_mediano_s}",
                  f"{f.asignado_tardios / f.asignado_verdad:.1%}")
    consola.print(t)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pedidos_rt", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", help="host:puerto del broker (por defecto KAFKA_BROKER o localhost:19092)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def con_generar(p):
        p.add_argument("--escala", type=float, default=1.0)
        p.add_argument("--seed", type=int, default=2026)

    p = sub.add_parser("generar"); con_generar(p); p.set_defaults(f=cmd_generar)
    p = sub.add_parser("publicar")
    p.add_argument("--velocidad", type=float, default=0.0, help="60 = una hora por minuto; 0 = sin pausas")
    p.add_argument("--reiniciar", action="store_true", help="borra y crea los tópicos")
    p.set_defaults(f=cmd_publicar)
    p = sub.add_parser("procesar")
    p.add_argument("--gracia", type=int, default=60, help="segundos de gracia de la ventana")
    p.add_argument("--grupo", default="metricas-operacion")
    p.add_argument("--carpeta", default="manual")
    p.add_argument("--espera", type=float, default=0.0, help="parar tras N s sin mensajes (0 = nunca)")
    p.set_defaults(f=cmd_procesar)
    p = sub.add_parser("evaluar")
    p.add_argument("--sin-procesar", action="store_true", help="reusa las salidas del flujo ya escritas")
    p.set_defaults(f=cmd_evaluar)
    p = sub.add_parser("todo"); con_generar(p); p.set_defaults(f=cmd_todo)
    p = sub.add_parser("en-vivo")
    p.add_argument("--velocidad", type=float, default=60.0)
    p.set_defaults(f=cmd_en_vivo)
    p = sub.add_parser("resumen"); p.set_defaults(f=cmd_resumen)

    a = ap.parse_args(argv)
    aj = Ajustes(broker=a.broker) if a.broker else Ajustes()
    a.f(a, aj)
