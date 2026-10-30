"""
Asignación determinística: el mismo usuario cae siempre en la misma variante de un
experimento, sin guardar estado, y la sal por experimento evita que los mismos
usuarios terminen siempre en tratamiento.
"""

from __future__ import annotations

import hashlib

import numpy as np

CUBETAS = 10_000


def cubeta(id_usuario: int, sal: str) -> int:
    h = hashlib.sha256(f"{sal}:{id_usuario}".encode()).digest()
    return int.from_bytes(h[:8], "big") % CUBETAS


def asignar(ids: np.ndarray, sal: str, reparto_tratamiento: float = 0.5) -> np.ndarray:
    """Devuelve True para tratamiento. `reparto_tratamiento` es la fracción esperada."""
    limite = int(round(reparto_tratamiento * CUBETAS))
    return np.fromiter((cubeta(int(i), sal) < limite for i in ids), dtype=bool, count=len(ids))
