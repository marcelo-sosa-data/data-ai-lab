"""
Codificadores de texto a vectores.

- `CodificadorLocal`: modelo multilingüe con fastembed (ONNX, corre en CPU, sin
  API). Se descarga una vez a datos/modelos/: multilingual-e5-large pesa
  ~2.2 GB; con EMBEDDINGS_MODELO se puede usar uno más liviano.
- `CodificadorHash`: trigramas de caracteres con hashing. No entiende nada,
  pero es determinista y no descarga nada: sirve para los tests.

Los vectores salen normalizados, así el producto punto es el coseno.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

import numpy as np

from .texto import normalizar

MODELO_DEFECTO = "intfloat/multilingual-e5-large"
MODELOS_COMPARADOS = [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "intfloat/multilingual-e5-large",
]


class Codificador(Protocol):
    nombre: str

    def codificar(self, textos: list[str], tipo: str = "pasaje") -> np.ndarray:
        """tipo: 'consulta' o 'pasaje' (los modelos e5 usan prefijos distintos)."""
        ...


def _normalizar_filas(m: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(normas == 0, 1, normas)


class CodificadorLocal:
    def __init__(self, modelo: str | None = None, cache: Path | None = None):
        from fastembed import TextEmbedding  # import diferido: BM25 solo no lo necesita

        self.nombre = modelo or os.getenv("EMBEDDINGS_MODELO", MODELO_DEFECTO)
        raiz = Path(__file__).parents[2]
        self._modelo = TextEmbedding(self.nombre, cache_dir=str(cache or raiz / "datos" / "modelos"))
        self._e5 = "e5" in self.nombre.lower()

    def codificar(self, textos: list[str], tipo: str = "pasaje") -> np.ndarray:
        if self._e5:
            prefijo = "query: " if tipo == "consulta" else "passage: "
            textos = [prefijo + t for t in textos]
        return _normalizar_filas(np.array(list(self._modelo.embed(textos)), dtype=np.float32))


class CodificadorHash:
    nombre = "hash-trigramas"

    def __init__(self, dimension: int = 512):
        self.dimension = dimension

    def codificar(self, textos: list[str], tipo: str = "pasaje") -> np.ndarray:
        m = np.zeros((len(textos), self.dimension), dtype=np.float32)
        for i, t in enumerate(textos):
            t = f"  {normalizar(t)}  "
            for j in range(len(t) - 2):
                h = int(hashlib.md5(t[j:j + 3].encode()).hexdigest()[:8], 16)
                m[i, h % self.dimension] += 1
        return _normalizar_filas(m)


def vectores_con_cache(codificador: Codificador, ids: list[str], textos: list[str],
                       ruta: Path | None) -> np.ndarray:
    """Codifica los pasajes y guarda el resultado; si el texto no cambió, lo reutiliza."""
    ruta = Path(ruta) if ruta else None
    huella = hashlib.sha256(("\n".join(textos) + codificador.nombre).encode()).hexdigest()[:16]
    if ruta and ruta.exists():
        guardado = np.load(ruta, allow_pickle=False)
        if str(guardado["huella"]) == huella and list(guardado["ids"]) == ids:
            return guardado["vectores"]
    vectores = codificador.codificar(textos, "pasaje")
    if ruta:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        np.savez(ruta, vectores=vectores, ids=np.array(ids), huella=np.array(huella))
    return vectores
