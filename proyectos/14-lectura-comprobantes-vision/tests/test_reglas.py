from datetime import date

import pytest

from comprobantes.esquema import Comprobante
from comprobantes.reglas import Contexto, digito_ruc, llave, registrar, ruc_valido, validar

EMPRESA = "20" + "45678912"
EMPRESA += str(digito_ruc(EMPRESA))
PROV = "20" + "11122233"
PROV += str(digito_ruc(PROV))
NO_HABIDO = "20" + "99988877"
NO_HABIDO += str(digito_ruc(NO_HABIDO))


@pytest.fixture
def contexto():
    return Contexto(
        ruc_empresa=EMPRESA,
        padron={PROV: {"razon_social": "PROVEEDOR SAC", "estado": "ACTIVO", "condicion": "HABIDO"},
                NO_HABIDO: {"razon_social": "FANTASMA SAC", "estado": "ACTIVO", "condicion": "NO HABIDO"}},
        ordenes={"OC-2026-01500": {"ruc_proveedor": PROV, "monto": 1200.0, "moneda": "PEN"}},
        fecha_recepcion=date(2026, 10, 10),
    )


def factura(**cambios) -> Comprobante:
    base = dict(tipo="factura", ruc_emisor=PROV, ruc_receptor=EMPRESA, serie="F001", numero=1500,
                fecha_emision=date(2026, 10, 8), moneda="PEN", base_imponible=1000.0, igv=180.0,
                total=1180.0, orden_compra="OC-2026-01500")
    return Comprobante(**{**base, **cambios})


def codigos(c, ctx):
    return {o.codigo for o in validar(c, ctx)}


def test_digito_verificador():
    assert ruc_valido(PROV) and ruc_valido(EMPRESA)
    otro = PROV[:10] + str((int(PROV[10]) + 1) % 10)
    assert not ruc_valido(otro)
    assert not ruc_valido("30111222333")    # prefijo que no existe
    assert not ruc_valido("2011122233")     # 10 dígitos
    # los restos 10 y 11 se convierten en 0 y 1
    assert all(digito_ruc(f"20{n:08d}") in range(10) for n in range(0, 2000, 7))


def test_comprobante_limpio_no_tiene_observaciones(contexto):
    assert codigos(factura(), contexto) == set()


@pytest.mark.parametrize("cambios, esperado", [
    (dict(igv=190.0, total=1190.0), "igv_no_cuadra"),
    (dict(total=1185.0), "total_no_cuadra"),
    (dict(ruc_receptor=PROV), "receptor_no_es_la_empresa"),
    (dict(ruc_emisor=NO_HABIDO), "proveedor_no_habido"),
    (dict(total=1300.0, igv=300.0), "excede_oc"),
    (dict(orden_compra="OC-2026-09999"), "oc_no_existe"),
    (dict(serie="B001"), "serie_no_corresponde"),
    (dict(fecha_emision=date(2026, 10, 20)), "fecha_futura"),
    (dict(igv=None), "campo_faltante"),
    (dict(ruc_emisor=PROV[:10] + str((int(PROV[10]) + 1) % 10)), "ruc_emisor_invalido"),
])
def test_cada_control(contexto, cambios, esperado):
    assert esperado in codigos(factura(**cambios), contexto)


def test_redondeo_de_igv_dentro_de_tolerancia(contexto):
    assert "igv_no_cuadra" not in codigos(factura(igv=180.07, total=1180.07), contexto)


def test_excede_oc_respeta_la_tolerancia(contexto):
    assert "excede_oc" not in codigos(factura(base_imponible=1026.0, igv=184.68, total=1210.68), contexto)


def test_duplicado_y_secuencia(contexto):
    c = factura()
    registrar(contexto, llave(c))
    assert "duplicado" in codigos(c, contexto)
    assert "duplicado" not in codigos(factura(numero=1512), contexto)
    assert "correlativo_fuera_de_secuencia" in codigos(factura(numero=15), contexto)
    assert "correlativo_fuera_de_secuencia" in codigos(factura(numero=150012), contexto)


def test_boleta_solo_avisa(contexto):
    b = factura(tipo="boleta", serie="B001", ruc_receptor=None, orden_compra=None)
    obs = validar(b, contexto)
    assert [(o.codigo, o.origen) for o in obs] == [("sin_credito_fiscal", "aviso")]
