"""
Validaciones que se le hacen a cada comprobante antes de registrarlo.

Mezclan dos tipos de control. Los aritméticos y de formato (dígito
verificador del RUC, IGV al 18%, total = base + IGV, serie según el tipo)
sirven igual para atrapar un error del proveedor que un error de lectura.
Los de negocio (RUC del receptor, padrón de SUNAT, orden de compra,
duplicado) solo se pueden hacer cruzando contra las tablas de la empresa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .esquema import Comprobante

TASA_IGV = 0.18
TOLERANCIA_IGV = 0.10       # S/ de diferencia aceptada por redondeo ítem a ítem
TOLERANCIA_OC = 0.01        # el total puede pasar la OC en 1% (fletes, redondeos)
SECUENCIA = (-500, 2000)    # rango esperado del correlativo respecto del último registrado
FACTORES_RUC = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def digito_ruc(primeros10: str) -> int:
    """Dígito verificador del RUC (módulo 11)."""
    suma = sum(int(c) * f for c, f in zip(primeros10, FACTORES_RUC))
    r = 11 - suma % 11
    return {10: 0, 11: 1}.get(r, r)


def ruc_valido(ruc: str | None) -> bool:
    if not ruc or not re.fullmatch(r"(10|15|17|20)\d{9}", ruc):
        return False
    return digito_ruc(ruc[:10]) == int(ruc[10])


@dataclass
class Observacion:
    codigo: str
    detalle: str
    origen: str  # "lectura", "aritmetica" (lectura o proveedor), "negocio" o "aviso" (solo informa)


@dataclass
class Contexto:
    """Lo que la empresa sabe al momento de recibir el comprobante."""
    ruc_empresa: str
    padron: dict[str, dict]                 # ruc -> {"razon_social", "estado", "condicion"}
    ordenes: dict[str, dict]                # oc -> {"ruc_proveedor", "monto", "moneda"}
    registrados: set[tuple] = field(default_factory=set)  # llaves ya registradas
    correlativos: dict[tuple, int] = field(default_factory=dict)  # (ruc, serie) -> último número
    fecha_recepcion: date | None = None


def llave(c: Comprobante) -> tuple:
    return (c.ruc_emisor, c.tipo, (c.serie or "").upper(), c.numero)


def registrar(ctx: Contexto, clave: tuple) -> None:
    """Deja el comprobante como registrado para los controles de duplicado y secuencia."""
    ctx.registrados.add(clave)
    ruc, _, serie, numero = clave
    if None not in (ruc, numero) and serie:
        ctx.correlativos[(ruc, serie)] = max(numero, ctx.correlativos.get((ruc, serie), 0))


REQUERIDOS = ["tipo", "ruc_emisor", "serie", "numero", "fecha_emision", "moneda",
              "base_imponible", "igv", "total"]


def validar(c: Comprobante, ctx: Contexto) -> list[Observacion]:
    obs: list[Observacion] = []
    faltan = [k for k in REQUERIDOS if getattr(c, k) is None]
    if c.tipo == "factura" and not c.ruc_receptor:
        faltan.append("ruc_receptor")
    if faltan:
        obs.append(Observacion("campo_faltante", ", ".join(faltan), "lectura"))

    if c.ruc_emisor and not ruc_valido(c.ruc_emisor):
        obs.append(Observacion("ruc_emisor_invalido", f"{c.ruc_emisor} no pasa el dígito verificador", "lectura"))
    if c.ruc_receptor and not ruc_valido(c.ruc_receptor):
        obs.append(Observacion("ruc_receptor_invalido", f"{c.ruc_receptor} no pasa el dígito verificador", "lectura"))

    if c.serie and c.tipo:
        patron = r"[FE][A-Z0-9]\d{2}" if c.tipo == "factura" else r"[BE][A-Z0-9]\d{2}"
        if not re.fullmatch(patron, c.serie.upper()):
            obs.append(Observacion("serie_no_corresponde", f"{c.serie} en una {c.tipo}", "lectura"))

    ultimo = ctx.correlativos.get((c.ruc_emisor, (c.serie or "").upper()))
    if ultimo is not None and c.numero is not None and \
            not ultimo + SECUENCIA[0] <= c.numero <= ultimo + SECUENCIA[1]:
        obs.append(Observacion("correlativo_fuera_de_secuencia",
                               f"{c.numero} cuando el último registrado de esa serie es {ultimo}", "lectura"))

    if c.fecha_emision and ctx.fecha_recepcion and c.fecha_emision > ctx.fecha_recepcion:
        obs.append(Observacion("fecha_futura", f"emitida {c.fecha_emision} y recibida {ctx.fecha_recepcion}", "lectura"))

    if None not in (c.base_imponible, c.igv):
        esperado = round(c.base_imponible * TASA_IGV, 2)
        if abs(c.igv - esperado) > TOLERANCIA_IGV:
            obs.append(Observacion("igv_no_cuadra", f"IGV {c.igv:,.2f}, el 18% de la base es {esperado:,.2f}", "aritmetica"))
    if None not in (c.base_imponible, c.igv, c.total):
        if abs(c.base_imponible + c.igv - c.total) > 0.02:
            obs.append(Observacion("total_no_cuadra",
                                   f"base + IGV = {c.base_imponible + c.igv:,.2f}, total {c.total:,.2f}", "aritmetica"))
    if c.items and c.base_imponible is not None:
        suma = round(sum(i.importe for i in c.items), 2)
        if abs(suma - c.base_imponible) > 0.05:
            obs.append(Observacion("items_no_suman", f"ítems {suma:,.2f}, base {c.base_imponible:,.2f}", "aritmetica"))

    # ---- contra las tablas de la empresa
    if c.tipo == "factura" and c.ruc_receptor and ruc_valido(c.ruc_receptor) and c.ruc_receptor != ctx.ruc_empresa:
        obs.append(Observacion("receptor_no_es_la_empresa", f"emitida al RUC {c.ruc_receptor}", "negocio"))

    if c.ruc_emisor and ruc_valido(c.ruc_emisor):
        prov = ctx.padron.get(c.ruc_emisor)
        if prov is None:
            obs.append(Observacion("proveedor_no_registrado", c.ruc_emisor, "negocio"))
        elif prov["condicion"] != "HABIDO" or prov["estado"] != "ACTIVO":
            obs.append(Observacion("proveedor_no_habido",
                                   f"{prov['razon_social']}: {prov['estado']} / {prov['condicion']}", "negocio"))

    if c.orden_compra:
        oc = ctx.ordenes.get(c.orden_compra.upper())
        if oc is None:
            obs.append(Observacion("oc_no_existe", c.orden_compra, "lectura"))
        else:
            if c.ruc_emisor and oc["ruc_proveedor"] != c.ruc_emisor:
                obs.append(Observacion("oc_de_otro_proveedor", c.orden_compra, "negocio"))
            if c.total is not None and c.moneda == oc["moneda"] and c.total > oc["monto"] * (1 + TOLERANCIA_OC):
                obs.append(Observacion("excede_oc",
                                       f"total {c.total:,.2f} contra OC por {oc['monto']:,.2f}", "negocio"))

    if c.tipo == "boleta":
        obs.append(Observacion("sin_credito_fiscal", "la boleta no da derecho a crédito fiscal", "aviso"))

    if None not in llave(c) and llave(c) in ctx.registrados:
        obs.append(Observacion("duplicado", f"{c.serie}-{c.numero} ya fue registrado", "negocio"))
    return obs
