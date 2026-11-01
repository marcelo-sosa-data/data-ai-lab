"""Formato de cifras según el `formato` que declara cada métrica en el YAML."""

from __future__ import annotations

import math


def valor(x: float, formato: str) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return {
        "soles": f"S/ {x:,.0f}",
        "soles_decimal": f"S/ {x:,.2f}",
        "entero": f"{x:,.0f}",
        "porcentaje": f"{x:.1%}",
        "porcentaje_fino": f"{x:.2%}",
    }[formato]


def cambio(base: float, actual: float, formato: str) -> str:
    """Las tasas cambian en puntos porcentuales; el resto, en porcentaje."""
    if formato.startswith("porcentaje"):
        return f"{(actual - base) * 100:+.2f} pp"
    return f"{actual / base - 1:+.1%}" if base else "-"


def contribucion(x: float, formato: str) -> str:
    if formato.startswith("porcentaje"):
        return f"{x * 100:+.2f} pp"
    if formato.startswith("soles"):
        return f"{'+' if x >= 0 else '-'}S/ {abs(x):,.2f}" if formato == "soles_decimal" else \
            f"{'+' if x >= 0 else '-'}S/ {abs(x):,.0f}"
    return f"{x:+,.0f}"
