"""
La macro de derivación que usa hoy la primera línea de atención.

El asesor lee el reclamo y lo manda a un área según palabras del texto, en este
orden. No consulta ningún sistema: decide solo con lo que escribió el cliente.
Se reproduce tal cual para medir cuántos reclamos llegan bien a la primera.
"""

from __future__ import annotations

import re
import unicodedata

FRAUDE = "Prevención de fraude"
BACKOFFICE = "Backoffice de tarjetas"
OPERACIONES = "Operaciones"
CONTRACARGOS = "Contracargos"

AREAS = [BACKOFFICE, OPERACIONES, FRAUDE, CONTRACARGOS]

# (patrón, área). Gana la primera que aparece en el texto.
REGLAS: list[tuple[str, str]] = [
    (r"fraude|estafa|robo|robaron|no reconozco|yo no hice|no hice|no autorice|no son mias", FRAUDE),
    (r"duplicad|doble|dos veces|2 veces", BACKOFFICE),
    (r"membresia|mantenimiento|cuota anual", BACKOFFICE),
    (r"pague|pago|abone|deposite", OPERACIONES),
    (r"recarga|saldo del celular", OPERACIONES),
    (r"no llego|nunca llego|no me entregaron|pedido|producto|compra por internet", CONTRACARGOS),
]


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def derivar(texto: str) -> str:
    """Área a la que la macro manda el reclamo. Si nada calza, va a Backoffice."""
    t = normalizar(texto)
    for patron, area in REGLAS:
        if re.search(patron, t):
            return area
    return BACKOFFICE
