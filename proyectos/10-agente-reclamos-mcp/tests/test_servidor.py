"""El servidor MCP revalida las reglas aunque el host no filtre nada."""

import asyncio
import json

import pytest
from mcp import Client

from conftest import caso
from reclamos.servidor import crear_servidor


def llamar(sistemas, *llamadas):
    """Ejecuta llamadas en orden contra el servidor en proceso; devuelve (texto, es_error) de cada una."""
    async def correr():
        salida = []
        async with Client(crear_servidor(sistemas)) as c:
            for nombre, args in llamadas:
                r = await c.call_tool(nombre, args)
                salida.append(("\n".join(x.text for x in r.content), r.is_error))
        return salida
    return asyncio.run(correr())


def test_catalogo_y_anotaciones(sistemas):
    async def listar():
        async with Client(crear_servidor(sistemas)) as c:
            return (await c.list_tools()).tools
    herramientas = {t.name: t for t in asyncio.run(listar())}
    assert set(herramientas) == {"ver_reclamo", "ver_cliente", "listar_movimientos", "revisar_cargo",
                                 "listar_pagos", "emitir_abono", "derivar_reclamo", "registrar_respuesta",
                                 "bloquear_tarjeta"}
    assert herramientas["listar_movimientos"].annotations.read_only_hint
    assert herramientas["bloquear_tarjeta"].annotations.destructive_hint
    motivo = herramientas["emitir_abono"].input_schema["properties"]["motivo"]
    assert set(motivo["enum"]) == {"cargo_duplicado", "recarga_no_acreditada", "membresia_exonerada"}


def test_el_reclamo_llega_enmascarado(sistemas, con):
    v = caso(con, "r.texto LIKE '%DNI es%'")
    (texto, error), = llamar(sistemas, ("ver_reclamo", {"id_reclamo": int(v["id_reclamo"])}))
    assert not error and "[DNI]" in json.loads(texto)["texto"]


def test_abono_de_un_duplicado_real_y_no_dos_veces(sistemas, con):
    v = caso(con, "caso = 'duplicado_real' AND accion_correcta = 'ABONAR'")
    abono = {"id_reclamo": int(v["id_reclamo"]), "id_movimiento": int(v["id_movimiento_ref"]),
             "monto": float(v["monto_abono"]), "motivo": "cargo_duplicado"}
    (r1, e1), (r2, e2) = llamar(sistemas, ("emitir_abono", abono), ("emitir_abono", abono))
    assert not e1 and json.loads(r1)["abono_registrado"]["monto"] == pytest.approx(v["monto_abono"])
    assert e2 and "dos veces" in r2


@pytest.mark.parametrize("caso_real, motivo, mensaje", [
    ("dos_compras_distintas", "cargo_duplicado", "no es un duplicado"),
    ("duplicado_revertido", "cargo_duplicado", ""),
    ("recarga_acreditada", "recarga_no_acreditada", "confirmó la recarga"),
    ("membresia_vencida", "membresia_exonerada", "fuera del periodo"),
])
def test_abono_sin_sustento_se_rechaza(sistemas, con, caso_real, motivo, mensaje):
    v = caso(con, f"caso = '{caso_real}'")
    monto = con.execute("SELECT monto FROM movimientos WHERE id_movimiento = ?",
                        [int(v["id_movimiento_ref"])]).fetchone()[0]
    (texto, error), = llamar(sistemas, ("emitir_abono", {
        "id_reclamo": int(v["id_reclamo"]), "id_movimiento": int(v["id_movimiento_ref"]),
        "monto": float(monto), "motivo": motivo}))
    assert error and mensaje in texto
    assert sistemas.ops.abonos == []


def test_tope_y_movimiento_de_otro_cliente(sistemas, con):
    v = caso(con, "accion_correcta = 'ESCALAR_SUPERVISOR'")
    monto = con.execute("SELECT monto FROM movimientos WHERE id_movimiento = ?",
                        [int(v["id_movimiento_ref"])]).fetchone()[0]
    otro = caso(con, f"caso = 'duplicado_real' AND id_reclamo <> {int(v['id_reclamo'])}")
    (t1, e1), (t2, e2) = llamar(
        sistemas,
        ("emitir_abono", {"id_reclamo": int(v["id_reclamo"]), "id_movimiento": int(v["id_movimiento_ref"]),
                          "monto": float(monto), "motivo": "cargo_duplicado"}),
        ("emitir_abono", {"id_reclamo": int(v["id_reclamo"]), "id_movimiento": int(otro["id_movimiento_ref"]),
                          "monto": float(otro["monto_abono"]), "motivo": "cargo_duplicado"}))
    assert e1 and "Supervisor" in t1
    assert e2 and "no pertenece" in t2


def test_respuesta_exige_lo_que_declara(sistemas, con):
    idr = int(caso(con, "caso = 'no_recibido'")["id_reclamo"])
    (t1, e1), (t2, e2), (t3, e3), (t4, e4) = llamar(
        sistemas,
        ("registrar_respuesta", {"id_reclamo": idr, "resultado": "derivado", "mensaje": "x"}),
        ("derivar_reclamo", {"id_reclamo": idr, "area": "Contracargos", "resumen": "Compra online no recibida"}),
        ("registrar_respuesta", {"id_reclamo": idr, "resultado": "derivado", "mensaje": "Derivado a Contracargos"}),
        ("derivar_reclamo", {"id_reclamo": idr, "area": "Operaciones", "resumen": "otra vez"}))
    assert e1 and "Primero deriva" in t1
    assert not e2 and not e3
    assert e4 and "cerrado" in t4
