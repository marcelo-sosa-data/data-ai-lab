"""
El proceso actual (AS IS) escrito como regla, para medirlo sobre los mismos
comprobantes.

Hoy una asistente digita cada comprobante en el ERP. El ERP bloquea un
duplicado exacto (mismo RUC, serie y número) y nada más. El contador revisa
el registro de compras al cierre, el día 12 del mes siguiente, cuando valida
los comprobantes en SUNAT y arma el PLE: ahí aparecen el IGV mal calculado,
el total que no cuadra, la factura emitida a otro RUC y el proveedor no
habido. Nadie compara la factura contra la orden de compra antes de pagar.
Tesorería paga al vencimiento.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

DIA_CIERRE = 12
SE_VE_AL_CIERRE = {"igv_mal", "total_mal", "receptor_errado", "no_habido"}
BLOQUEA_EL_ERP = {"duplicado"}
TIPO_CAMBIO = 3.75  # solo para sumar montos en dólares a soles


def fecha_cierre(recepcion: date) -> date:
    anio, mes = (recepcion.year + 1, 1) if recepcion.month == 12 else (recepcion.year, recepcion.month + 1)
    return date(anio, mes, DIA_CIERRE)


def deteccion_as_is(verdad: pd.DataFrame) -> pd.DataFrame:
    """Para cada comprobante con error del proveedor: cuándo se detecta hoy y si ya se pagó."""
    v = verdad[verdad["anomalia"].notna()].copy()
    recep = pd.to_datetime(v["fecha_recepcion"]).dt.date
    v["fecha_deteccion"] = [
        r if a in BLOQUEA_EL_ERP else (fecha_cierre(r) if a in SE_VE_AL_CIERRE else None)
        for a, r in zip(v["anomalia"], recep)
    ]
    v["detectado"] = v["fecha_deteccion"].notna()
    vence = pd.to_datetime(v["fecha_vencimiento"]).dt.date
    v["pagado_antes"] = [
        (a not in BLOQUEA_EL_ERP) and (d is None or vto < d)
        for a, d, vto in zip(v["anomalia"], v["fecha_deteccion"], vence)
    ]
    v["dias_a_deteccion"] = [(d - r).days if d else None for d, r in zip(v["fecha_deteccion"], recep)]
    v["monto_soles"] = v["total"] * v["moneda"].map({"PEN": 1.0, "USD": TIPO_CAMBIO})
    return v[["doc_id", "anomalia", "fecha_recepcion", "fecha_vencimiento", "fecha_deteccion",
              "detectado", "pagado_antes", "dias_a_deteccion", "monto_soles"]]
