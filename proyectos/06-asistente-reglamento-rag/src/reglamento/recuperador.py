"""
Búsqueda de artículos: BM25, vectores o ambos con fusión por rangos (RRF).

La fecha de la consulta filtra antes de rankear: un artículo derogado no
compite. Sin ese filtro, el texto original y el modificado son casi iguales y
cuál sale primero depende de detalles del puntaje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from .bm25 import BM25
from .corpus import Fragmento
from .embeddings import Codificador, vectores_con_cache
from .texto import terminos

RRF_K = 60


@dataclass(frozen=True)
class Configuracion:
    nombre: str
    lexico: bool = True
    sinonimos: bool = True
    vectorial: bool = True
    vigencia: bool = True
    peso_vectorial: float = 0.5   # en la fusión: 0.5 es RRF clásico


CONFIGURACIONES = {c.nombre: c for c in [
    Configuracion("bm25", sinonimos=False, vectorial=False),
    Configuracion("bm25+sinonimos", vectorial=False),
    Configuracion("hibrido rrf", peso_vectorial=0.5),
    Configuracion("hibrido 0.8", peso_vectorial=0.8),
    Configuracion("vectorial", lexico=False, sinonimos=False),
    Configuracion("vectorial sin vigencia", lexico=False, sinonimos=False, vigencia=False),
]}
# elegida con las preguntas de desarrollo (ver README); sin modelo de vectores se usa bm25+sinonimos
DEFECTO = CONFIGURACIONES["vectorial"]
SIN_VECTORES = CONFIGURACIONES["bm25+sinonimos"]


@dataclass
class Resultado:
    fragmento: Fragmento
    puntaje: float          # el que ordena (RRF en híbrido, BM25 o coseno si va solo)
    bm25: float
    coseno: float | None


@dataclass
class Busqueda:
    resultados: list[Resultado]
    confianza: float        # coseno del mejor candidato; sin vectores, BM25 del mejor

    @property
    def ids(self) -> list[str]:
        return [r.fragmento.id for r in self.resultados]


def _rangos(puntajes: np.ndarray, candidatos: np.ndarray) -> np.ndarray:
    """Rango 1..n dentro de los candidatos (los demás quedan en infinito)."""
    rangos = np.full(len(puntajes), np.inf)
    idx = np.flatnonzero(candidatos)
    orden = idx[np.argsort(-puntajes[idx], kind="stable")]
    rangos[orden] = np.arange(1, len(orden) + 1)
    return rangos


class Recuperador:
    def __init__(self, fragmentos: list[Fragmento], codificador: Codificador | None = None,
                 ruta_cache: Path | None = None):
        self.fragmentos = fragmentos
        textos = [f.texto_indexable for f in fragmentos]
        self.bm25 = BM25([terminos(t) for t in textos])
        self.codificador = codificador
        self.vectores = (vectores_con_cache(codificador, [f.id for f in fragmentos], textos, ruta_cache)
                         if codificador else None)
        self._consultas: dict[str, np.ndarray] = {}

    def precodificar(self, preguntas: list[str]) -> None:
        """Codifica en lote las preguntas que faltan (la evaluación las repite en cada configuración)."""
        faltan = [p for p in dict.fromkeys(preguntas) if p not in self._consultas]
        if faltan and self.codificador:
            for p, v in zip(faltan, self.codificador.codificar(faltan, "consulta")):
                self._consultas[p] = v

    def _vector_consulta(self, pregunta: str) -> np.ndarray:
        if pregunta not in self._consultas:
            self.precodificar([pregunta])
        return self._consultas[pregunta]

    def buscar(self, pregunta: str, fecha: date, k: int = 5,
               config: Configuracion = DEFECTO) -> Busqueda:
        if config.vectorial and self.codificador is None:
            raise ValueError(f"La configuración '{config.nombre}' necesita un codificador de vectores.")
        n = len(self.fragmentos)
        candidatos = (np.array([f.vigente(fecha) for f in self.fragmentos]) if config.vigencia
                      else np.ones(n, dtype=bool))

        bm25 = self.bm25.puntajes(terminos(pregunta, con_sinonimos=config.sinonimos))
        coseno = None
        if config.vectorial:
            coseno = self.vectores @ self._vector_consulta(pregunta)

        if config.lexico and config.vectorial:
            w = config.peso_vectorial
            puntaje = ((1 - w) / (RRF_K + _rangos(bm25, candidatos))
                       + w / (RRF_K + _rangos(coseno, candidatos)))
        elif config.vectorial:
            puntaje = coseno.copy()
        else:
            puntaje = bm25.copy()
        puntaje = np.where(candidatos, puntaje, -np.inf)

        orden = np.argsort(-puntaje, kind="stable")[:k]
        resultados = [Resultado(self.fragmentos[i], float(puntaje[i]), float(bm25[i]),
                                None if coseno is None else float(coseno[i])) for i in orden]
        if coseno is not None:
            confianza = float(coseno[candidatos].max())
        else:
            confianza = float(bm25[candidatos].max())
        return Busqueda(resultados, confianza)
