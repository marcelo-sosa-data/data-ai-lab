"""
Regla de decisión escrita antes de ver los datos, para que la lectura no dependa de
quién la haga ni de cuánto quiere que gane su feature.

  1. SRM con p < 0.001                      → invalidar (no se lee nada más)
  2. algún guardrail con daño significativo  → no lanzar
  3. primaria positiva y guardrails dentro   → lanzar
     de su margen de no inferioridad
  4. primaria positiva y algún guardrail     → extender (falta muestra para
     sin concluir                              descartar el daño)
  5. primaria sin efecto o negativa          → no lanzar
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalogo import METRICAS, Experimento
from .estadistica import Comparacion

UMBRAL_SRM = 0.001


@dataclass
class EstadoGuardrail:
    metrica: str
    margen: float
    estado: str  # ok | daño | sin concluir
    peor_caso: float  # extremo malo del IC relativo, en la dirección mala (positivo = daño)


@dataclass
class Decision:
    veredicto: str  # lanzar | no lanzar | extender | invalidar
    motivo: str
    guardrails: list[EstadoGuardrail]


def evaluar_guardrail(metrica: str, margen: float, c: Comparacion) -> EstadoGuardrail:
    mejor = METRICAS[metrica]["mejor"]
    # se expresa todo como "daño relativo": positivo es malo
    peor = -c.relativo_bajo if mejor > 0 else c.relativo_alto
    mejor_caso = -c.relativo_alto if mejor > 0 else c.relativo_bajo
    if peor <= margen:
        estado = "ok"
    elif mejor_caso > 0:
        estado = "daño"
    else:
        estado = "sin concluir"
    return EstadoGuardrail(metrica, margen, estado, float(peor))


def _pct(x: float) -> str:
    return f"{x:+.1%}"


def _may(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


def alerta_novedad(semanas) -> str:
    """Avisa si el efecto de la primera semana no se sostiene después."""
    if semanas is None or not len(semanas) or not {"1", "2+"} <= set(semanas.semana):
        return ""
    s1 = semanas.set_index("semana").loc["1"]
    resto = semanas.set_index("semana").loc["2+"]
    if s1.p_valor < 0.05 and resto.relativo_alto < s1.relativo and resto.relativo < s1.relativo / 2:
        return (f" Ojo con el efecto novedad: {_pct(s1.relativo)} la primera semana y {_pct(resto.relativo)} "
                f"(IC {_pct(resto.relativo_bajo)} a {_pct(resto.relativo_alto)}) después; lo que queda es "
                "menos de lo que dice el total.")
    return ""


def decidir(exp: Experimento, p_srm: float, lecturas: dict[str, Comparacion],
            n_control: int, n_tratamiento: int, semanas=None) -> Decision:
    if p_srm < UMBRAL_SRM:
        esperado = exp.reparto
        real = n_tratamiento / (n_control + n_tratamiento)
        return Decision("invalidar", f"SRM: {real:.1%} de los expuestos en tratamiento cuando se esperaba "
                                     f"{esperado:.0%} (p = {p_srm:.1e}). Hay un problema de asignación o de "
                                     "registro; el efecto medido no es confiable.", [])

    gs = [evaluar_guardrail(g.metrica, g.margen, lecturas[g.metrica]) for g in exp.guardrails]
    prim = lecturas[exp.primaria]
    nombre = METRICAS[exp.primaria]["nombre"]
    ic = f"{_pct(prim.relativo)} (IC 95% {_pct(prim.relativo_bajo)} a {_pct(prim.relativo_alto)})"
    danos = [g for g in gs if g.estado == "daño"]
    if danos:
        d = ", ".join(f"{METRICAS[g.metrica]['nombre']} {_pct(lecturas[g.metrica].relativo)}" for g in danos)
        return Decision("no lanzar", f"{_may(nombre)} {ic}, pero rompe guardrails: {d}.", gs)

    positiva = prim.relativo_bajo > 0 if METRICAS[exp.primaria]["mejor"] > 0 else prim.relativo_alto < 0
    if positiva:
        pendientes = [g for g in gs if g.estado == "sin concluir"]
        if pendientes:
            d = ", ".join(f"{METRICAS[g.metrica]['nombre']} (no se descarta "
                          f"{_pct(-g.peor_caso if METRICAS[g.metrica]['mejor'] > 0 else g.peor_caso)})"
                          for g in pendientes)
            return Decision("extender", f"{_may(nombre)} {ic}. Falta muestra para descartar daño en: {d}.",
                            gs)
        return Decision("lanzar", f"{_may(nombre)} {ic} y los guardrails dentro de su margen."
                        + alerta_novedad(semanas), gs)
    if prim.p_valor < 0.05:
        return Decision("no lanzar", f"{_may(nombre)} empeora: {ic}.", gs)
    return Decision("no lanzar", f"Sin efecto detectable en {nombre}: {ic}.", gs)
