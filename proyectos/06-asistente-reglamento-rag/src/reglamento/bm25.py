"""BM25 (Okapi) sobre listas de términos. Corto a propósito para poder testearlo entero."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np


class BM25:
    def __init__(self, documentos: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.frecuencias = [Counter(d) for d in documentos]
        self.largos = np.array([len(d) for d in documentos], dtype=float)
        self.largo_medio = float(self.largos.mean()) if len(documentos) else 0.0
        n = len(documentos)
        df = Counter(t for d in documentos for t in set(d))
        # idf con +1 dentro del log: nunca negativo aunque el término esté en más de la mitad
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def puntajes(self, consulta: list[str]) -> np.ndarray:
        salida = np.zeros(len(self.frecuencias))
        norma = self.k1 * (1 - self.b + self.b * self.largos / (self.largo_medio or 1))
        for termino in set(consulta):
            idf = self.idf.get(termino)
            if idf is None:
                continue
            tf = np.array([f.get(termino, 0) for f in self.frecuencias], dtype=float)
            salida += idf * tf * (self.k1 + 1) / (tf + norma)
        return salida
