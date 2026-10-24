"""
Corre el set de evaluación y deja un reporte en evals/resultados/.

    python evals/evaluar.py              # con el LLM configurado en .env
    python evals/evaluar.py --demo       # verifica que el pipeline funciona
    python evals/evaluar.py --solo e05 e11
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from text2sql.cli import cargar_env, crear_agente  # noqa: E402
from text2sql.evaluacion import resultados_equivalentes  # noqa: E402

consola = Console()


def main() -> None:
    cargar_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--modelo")
    parser.add_argument("--db", type=Path, default=RAIZ / "datos" / "minimarkets.duckdb")
    parser.add_argument("--solo", nargs="*", help="IDs de casos a correr")
    parser.add_argument("--sin-reporte", action="store_true")
    args = parser.parse_args()

    casos = json.loads((RAIZ / "evals" / "casos.json").read_text(encoding="utf-8"))
    if args.solo:
        casos = [c for c in casos if c["id"] in args.solo]

    agente = crear_agente(args.demo, args.db, args.modelo)
    db = agente.db

    filas_reporte = []
    tabla = Table(title=f"Evaluación · {agente.modelo.nombre}")
    for col in ["id", "dificultad", "ok", "pasos", "corregidas", "tokens", "seg"]:
        tabla.add_column(col)

    for caso in casos:
        ref = db.ejecutar(caso["sql"])
        assert ref.ok, f"El SQL de referencia de {caso['id']} falla: {ref.error}"

        with consola.status(f"{caso['id']}: {caso['pregunta'][:60]}..."):
            res = agente.preguntar(caso["pregunta"])

        correcto = res.ok and resultados_equivalentes(res.filas, ref.filas)
        tokens = res.tokens_entrada + res.tokens_salida
        filas_reporte.append({
            "id": caso["id"], "dificultad": caso["dificultad"], "pregunta": caso["pregunta"],
            "correcto": correcto, "pasos": len(res.pasos),
            "corregidas": res.consultas_fallidas, "tokens": tokens,
            "segundos": round(res.segundos, 2), "respuesta": res.respuesta, "sql": res.sql,
        })
        tabla.add_row(caso["id"], caso["dificultad"], "✅" if correcto else "❌",
                      str(len(res.pasos)), str(res.consultas_fallidas),
                      f"{tokens:,}", f"{res.segundos:.1f}")

    consola.print(tabla)

    total = len(filas_reporte)
    aciertos = sum(f["correcto"] for f in filas_reporte)
    por_dif = defaultdict(lambda: [0, 0])
    for f in filas_reporte:
        por_dif[f["dificultad"]][0] += f["correcto"]
        por_dif[f["dificultad"]][1] += 1

    consola.print(f"\n[bold]Execution accuracy: {aciertos}/{total} "
                  f"({100 * aciertos / total:.0f}%)[/]")
    for dif, (a, n) in por_dif.items():
        consola.print(f"  {dif:<8} {a}/{n}")

    if args.demo:
        consola.print("\n[yellow]Modo demo: usa el SQL de referencia, así que el 100% solo "
                      "confirma que el pipeline funciona. No mide al modelo.[/]")
        return
    if args.sin_reporte:
        return

    carpeta = RAIZ / "evals" / "resultados"
    carpeta.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H%M")
    nombre = f"{marca}_{agente.modelo.nombre}"
    (carpeta / f"{nombre}.json").write_text(
        json.dumps(filas_reporte, ensure_ascii=False, indent=2), encoding="utf-8")

    lineas = [
        f"# Evaluación {marca} · {agente.modelo.nombre}", "",
        f"**Execution accuracy:** {aciertos}/{total} ({100 * aciertos / total:.0f}%)", "",
        "| Dificultad | Aciertos |", "|---|---|",
        *[f"| {d} | {a}/{n} |" for d, (a, n) in por_dif.items()], "",
        "| ID | OK | Pasos | Corregidas | Tokens | Seg | Pregunta |", "|---|---|---|---|---|---|---|",
        *[f"| {f['id']} | {'✅' if f['correcto'] else '❌'} | {f['pasos']} | {f['corregidas']} | "
          f"{f['tokens']:,} | {f['segundos']} | {f['pregunta']} |" for f in filas_reporte],
    ]
    (carpeta / f"{nombre}.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    consola.print(f"\nReporte guardado en evals/resultados/{nombre}.md")


if __name__ == "__main__":
    main()
