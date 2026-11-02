"""
El flujo completo: buscar, decidir si hay con qué responder, redactar y
verificar las citas.

Dos puntos donde el asistente prefiere no responder:
1. antes del modelo, si la búsqueda no encontró nada parecido (confianza bajo
   el umbral): no se gasta una llamada ni se le da al modelo material ajeno;
2. después, si el modelo dice que no alcanza o si no cita ningún artículo
   de los que recibió. Sin cita no hay respuesta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

from .corpus import Fragmento
from .llm import Modelo
from .recuperador import DEFECTO, Busqueda, Configuracion, Recuperador

MENSAJE_SIN_RESPUESTA = ("No encontré eso en los reglamentos vigentes. Escribe a Registros Académicos "
                         "para que te orienten.")


@dataclass
class Respuesta:
    pregunta: str
    fecha: date
    texto: str
    citas: list[Fragmento]
    busqueda: Busqueda
    abstencion: str | None = None      # None, "confianza", "modelo" o "sin_citas"
    citas_descartadas: list[int] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos: float = 0.0

    @property
    def respondio(self) -> bool:
        return self.abstencion is None


class Asistente:
    def __init__(self, recuperador: Recuperador, modelo: Modelo, umbral: float,
                 k: int = 5, config: Configuracion = DEFECTO):
        self.recuperador, self.modelo = recuperador, modelo
        self.umbral, self.k, self.config = umbral, k, config

    def preguntar(self, pregunta: str, fecha: date | None = None) -> Respuesta:
        inicio = time.perf_counter()
        fecha = fecha or date.today()
        busqueda = self.recuperador.buscar(pregunta, fecha, self.k, self.config)

        def cerrar(**kw) -> Respuesta:
            return Respuesta(pregunta, fecha, busqueda=busqueda,
                             segundos=time.perf_counter() - inicio, **kw)

        if busqueda.confianza < self.umbral:
            return cerrar(texto=MENSAJE_SIN_RESPUESTA, citas=[], abstencion="confianza")

        fragmentos = [r.fragmento for r in busqueda.resultados]
        red = self.modelo.redactar(pregunta, fragmentos)
        tokens = {"tokens_entrada": red.tokens_entrada, "tokens_salida": red.tokens_salida}
        validas = [c for c in dict.fromkeys(red.citas) if 1 <= c <= len(fragmentos)]
        descartadas = [c for c in red.citas if c not in validas]

        if red.sin_respuesta:
            return cerrar(texto=MENSAJE_SIN_RESPUESTA, citas=[], abstencion="modelo", **tokens)
        if not validas:
            return cerrar(texto=MENSAJE_SIN_RESPUESTA, citas=[], abstencion="sin_citas",
                          citas_descartadas=descartadas, **tokens)
        return cerrar(texto=red.texto, citas=[fragmentos[c - 1] for c in validas],
                      citas_descartadas=descartadas, **tokens)
