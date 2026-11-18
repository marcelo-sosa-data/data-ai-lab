"""
Decide si un comprobante se registra solo o pasa a la bandeja de revisión.

Pasa a revisión si alguna validación falla (salvo los avisos, que solo
informan) o si algún campo obligatorio se leyó con confianza bajo el umbral.
Tesseract no da la misma escala de confianza para todos los campos: un
monto limpio sale con 0.96 y una serie como F001-00012345, que mezcla letras
y dígitos, rara vez pasa de 0.8 aunque esté bien leída. Por eso el umbral es
por campo. No se fija a ojo: se calibra con setiembre y se mide en octubre
(ver evaluacion.umbrales_por_campo).
"""

from __future__ import annotations

from dataclasses import dataclass

from .esquema import Comprobante
from .reglas import REQUERIDOS, Observacion

# Para relacionar cada error sembrado con el motivo que debería levantarlo
MOTIVO_DE_ANOMALIA = {
    "igv_mal": "igv_no_cuadra",
    "total_mal": "total_no_cuadra",
    "receptor_errado": "receptor_no_es_la_empresa",
    "excede_oc": "excede_oc",
    "no_habido": "proveedor_no_habido",
    "duplicado": "duplicado",
}


@dataclass
class Decision:
    destino: str            # "aprobado" o "revision"
    motivos: list[str]
    campos_dudosos: list[str]


def decidir(c: Comprobante, confianza: dict[str, float] | None, obs: list[Observacion],
            umbral: float | dict[str, float]) -> Decision:
    motivos = [o.codigo for o in obs if o.origen != "aviso"]
    dudosos: list[str] = []
    if confianza:  # el LLM no entrega confianza por campo: ahí solo deciden las validaciones
        campos = REQUERIDOS + (["ruc_receptor"] if c.tipo == "factura" else []) + \
            (["orden_compra"] if c.orden_compra else [])
        limite = umbral if isinstance(umbral, dict) else dict.fromkeys(campos, umbral)
        dudosos = [k for k in campos if getattr(c, k) is not None and confianza.get(k, 0.0) < limite.get(k, 0.0)]
        if dudosos:
            motivos.append("lectura_dudosa")
    return Decision("revision" if motivos else "aprobado", motivos, dudosos)
