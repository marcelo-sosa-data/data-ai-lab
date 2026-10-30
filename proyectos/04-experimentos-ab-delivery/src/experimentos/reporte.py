"""
Readout en Markdown de un experimento, listo para pegar en el canal del equipo o en
la wiki. Sale de la misma lectura que el tablero, así no hay dos versiones de la cifra.
"""

from __future__ import annotations

import pandas as pd

from .analisis import Lectura
from .calendario import rango
from .catalogo import DIAS_PRE, METRICAS
from .resultados import DIAS_MINIMOS

ESTADOS = {"ok": "dentro del margen", "daño": "daño", "sin concluir": "sin concluir"}
DIMENSIONES = {"region": "región", "tipo_usuario": "tipo de usuario", "plataforma": "plataforma"}


def _v(metrica: str, x: float) -> str:
    return format(x, METRICAS[metrica]["formato"])


def _p(x: float) -> str:
    return "<0.001" if x < 0.001 else f"{x:.3f}"


def readout(lec: Lectura, generado: pd.Timestamp | None = None) -> str:
    e, d = lec.experimento, lec.decision
    generado = generado or pd.Timestamp.now().floor("min")
    n = lec.n_control + lec.n_tratamiento
    out = [
        f"# {e.id} · {e.nombre}",
        "",
        f"**Veredicto: {d.veredicto}.** {d.motivo}",
        "",
        f"- Hipótesis: {e.hipotesis}",
        f"- Ventana: {rango(e.inicio, e.fin)} · {n:,} usuarios expuestos "
        f"({lec.n_control:,} control, {lec.n_tratamiento:,} tratamiento)",
        f"- SRM: p = {lec.p_srm:.2g}" + (" **(desbalance: no leer los efectos)**" if d.veredicto == "invalidar"
                                         else ""),
        "",
    ]
    if d.veredicto == "invalidar":
        out += ["## Dónde está el desbalance", "", "| versión de la app | control | tratamiento | % tratamiento | p SRM |",
                "|---|---:|---:|---:|---:|"]
        for r in lec.srm_por_version.itertuples():
            out.append(f"| {r.version_app} | {r.control:,} | {r.tratamiento:,} | {r.pct_tratamiento:.1%} | "
                       f"{r.p_srm:.2g} |")
        out.append("")

    out += ["## Métricas", "",
            "| métrica | rol | control | tratamiento | efecto | IC 95% | p | método |",
            "|---|---|---:|---:|---:|---|---:|---|"]
    for r in lec.metricas.itertuples():
        out.append(f"| {r.nombre} | {r.rol} | {_v(r.metrica, r.media_control)} | "
                   f"{_v(r.metrica, r.media_tratamiento)} | {r.relativo:+.1%} | "
                   f"{r.relativo_bajo:+.1%} a {r.relativo_alto:+.1%} | {_p(r.p_valor)} | {r.metodo} |")
    prim = lec.lecturas[e.primaria]
    if prim.reduccion_varianza:
        out += ["", f"CUPED con los {DIAS_PRE} días previos baja la varianza de la primaria en "
                    f"{prim.reduccion_varianza:.0%}."]

    if d.guardrails:
        out += ["", "## Guardrails", "", "| métrica | margen tolerado | peor caso (IC) | estado |", "|---|---:|---:|---|"]
        for g in d.guardrails:
            out.append(f"| {METRICAS[g.metrica]['nombre']} | {g.margen:.0%} | {g.peor_caso:+.1%} | "
                       f"{ESTADOS[g.estado]} |")

    if len(lec.segmentos):
        out += ["", f"## Segmentos ({METRICAS[e.primaria]['nombre']})", "",
                "| dimensión | segmento | efecto | IC 95% | q (BH) |", "|---|---|---:|---|---:|"]
        for r in lec.segmentos.itertuples():
            out.append(f"| {DIMENSIONES[r.dimension]} | {r.segmento} | {r.relativo:+.1%} | "
                       f"{r.relativo_bajo:+.1%} a {r.relativo_alto:+.1%} | {_p(r.q_valor)} |")

    if len(lec.semanas):
        out += ["", "## Efecto por semana desde la exposición", "", "| semana | usuarios | efecto | IC 95% |",
                "|---|---:|---:|---|"]
        for r in lec.semanas.itertuples():
            out.append(f"| {r.semana} | {r.n_control + r.n_tratamiento:,} | {r.relativo:+.1%} | "
                       f"{r.relativo_bajo:+.1%} a {r.relativo_alto:+.1%} |")

    s = lec.secuencial
    parada = s[(s.p_siempre_valido < 0.05) & (s.dia >= DIAS_MINIMOS)]
    out += ["", "## Lectura secuencial", ""]
    if len(parada):
        out.append(f"El p-valor siempre válido (mSPRT) estaba bajo 0.05 el día {int(parada.dia.iloc[0])} de "
                   f"{len(s)} (se exige al menos una semana completa): con esta regla se podía parar ahí "
                   "para la primaria, si los guardrails también estaban leídos.")
    else:
        out.append(f"El p-valor siempre válido (mSPRT) no bajó de 0.05 en los {len(s)} días.")
    out += ["", f"_Generado el {generado:%d/%m/%Y %H:%M} con `python -m experimentos reporte {e.id}`._", ""]
    return "\n".join(out)
