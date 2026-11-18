"""
Lo que se extrae de un comprobante y cómo se compara contra la verdad.

El mismo modelo de pydantic sirve para tres cosas: validar lo que devuelve
el extractor, generar el JSON schema que se le pide al LLM (salida
estructurada estricta) y normalizar antes de comparar campo por campo.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CAMPOS = ["tipo", "ruc_emisor", "ruc_receptor", "serie", "numero", "fecha_emision",
          "moneda", "base_imponible", "igv", "total", "orden_compra"]
CAMPOS_MONTO = ["base_imponible", "igv", "total"]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descripcion: str
    cantidad: float
    valor_unitario: float = Field(description="Valor unitario sin IGV")
    importe: float = Field(description="Cantidad por valor unitario, sin IGV")


class Comprobante(BaseModel):
    """Campos de una factura o boleta electrónica peruana (representación impresa)."""

    model_config = ConfigDict(extra="forbid")
    tipo: Literal["factura", "boleta"] | None = None
    ruc_emisor: str | None = Field(None, description="RUC de 11 dígitos de quien emite")
    ruc_receptor: str | None = Field(None, description="RUC del cliente; vacío si es boleta sin RUC")
    serie: str | None = Field(None, description="4 caracteres, por ejemplo F001, E001 o B002")
    numero: int | None = Field(None, description="Correlativo sin ceros a la izquierda")
    fecha_emision: date | None = None
    moneda: Literal["PEN", "USD"] | None = None
    base_imponible: float | None = Field(None, description="Operación gravada o valor de venta, sin IGV")
    igv: float | None = None
    total: float | None = Field(None, description="Importe total del comprobante")
    orden_compra: str | None = Field(None, description="Formato OC-AAAA-NNNNN si aparece")
    items: list[Item] = Field(default_factory=list)


def esquema_json() -> dict:
    """JSON schema estricto para `response_format` (todos los campos requeridos)."""
    esquema = Comprobante.model_json_schema()

    def endurecer(nodo: dict) -> None:
        if nodo.get("type") == "object" or "properties" in nodo:
            nodo["required"] = list(nodo.get("properties", {}))
            nodo["additionalProperties"] = False
        for v in nodo.get("properties", {}).values():
            v.pop("default", None)
            endurecer(v)
        for v in nodo.get("$defs", {}).values():
            endurecer(v)
        if "items" in nodo and isinstance(nodo["items"], dict):
            endurecer(nodo["items"])

    endurecer(esquema)
    return esquema


def redondear(x: float | None) -> float | None:
    if x is None:
        return None
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalizar(campo: str, valor):
    """Forma canónica de un campo para comparar extraído contra verdad."""
    if valor is None or valor == "":
        return None
    if campo in CAMPOS_MONTO:
        return redondear(float(valor))
    if campo in ("ruc_emisor", "ruc_receptor"):
        return re.sub(r"\D", "", str(valor)) or None
    if campo == "serie":
        return str(valor).strip().upper()
    if campo == "numero":
        return int(valor)
    if campo == "fecha_emision":
        return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])
    if campo == "orden_compra":
        return str(valor).strip().upper()
    return valor


def comparar(extraido: Comprobante, verdad: dict) -> dict[str, bool]:
    """Acierto por campo. Un campo ausente en ambos lados cuenta como acierto."""
    return {c: normalizar(c, getattr(extraido, c)) == normalizar(c, verdad.get(c)) for c in CAMPOS}
