"""
Comparación de resultados para el set de evaluación ("execution accuracy").

No se compara el texto del SQL (hay mil formas de escribir la misma consulta),
sino lo que devuelve. Se acepta como correcto si:
  - cada columna de la respuesta de referencia aparece en la del agente
    (con cualquier nombre y en cualquier orden),
  - las filas coinciden sin importar el orden,
  - los números coinciden con una tolerancia chica (redondeos).
Columnas extra en la respuesta del agente no penalizan.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from itertools import permutations


def _norm(v):
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip()
    return v


def _iguales(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=5e-3, abs_tol=0.051)
    return a == b


def _clave(v):
    # para ordenar mezclando tipos sin que Python reclame
    return (v is None, type(v).__name__, v if v is not None else 0)


def _columna(filas, i):
    return sorted((_norm(f[i]) for f in filas), key=_clave)


def _misma_columna(a: list, b: list) -> bool:
    return len(a) == len(b) and all(_iguales(x, y) for x, y in zip(a, b))


def resultados_equivalentes(filas_agente: list, filas_ref: list) -> bool:
    if len(filas_agente) != len(filas_ref):
        return False
    if not filas_ref:
        return True

    n_ref = len(filas_ref[0])
    n_ag = len(filas_agente[0])
    if n_ag < n_ref:
        return False

    # candidatos: columnas del agente con los mismos valores que cada columna de referencia
    candidatos = []
    for i in range(n_ref):
        col_ref = _columna(filas_ref, i)
        opciones = [j for j in range(n_ag) if _misma_columna(_columna(filas_agente, j), col_ref)]
        if not opciones:
            return False
        candidatos.append(opciones)

    # se prueba cada asignación posible y se comparan filas completas
    ref = sorted((tuple(_norm(v) for v in f) for f in filas_ref), key=lambda t: [_clave(x) for x in t])
    for asignacion in permutations(range(n_ag), n_ref):
        if any(asignacion[i] not in candidatos[i] for i in range(n_ref)):
            continue
        proy = sorted((tuple(_norm(f[j]) for j in asignacion) for f in filas_agente),
                      key=lambda t: [_clave(x) for x in t])
        if all(all(_iguales(a, b) for a, b in zip(fa, fr)) for fa, fr in zip(proy, ref)):
            return True
    return False
