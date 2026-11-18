from datetime import date

from comprobantes.esquema import CAMPOS, Comprobante, comparar, esquema_json, normalizar


def test_esquema_estricto_para_el_llm():
    e = esquema_json()
    assert e["additionalProperties"] is False
    assert set(e["required"]) == set(Comprobante.model_fields)
    item = e["$defs"]["Item"]
    assert item["additionalProperties"] is False and set(item["required"]) == {
        "descripcion", "cantidad", "valor_unitario", "importe"}
    assert all("default" not in p for p in e["properties"].values())


def test_normalizar():
    assert normalizar("numero", "00012345") == 12345
    assert normalizar("ruc_emisor", "20 1234 5678 9") == "20123456789"
    assert normalizar("total", 1180.005) == 1180.01
    assert normalizar("fecha_emision", "2026-10-08") == date(2026, 10, 8)
    assert normalizar("serie", " f001 ") == "F001"
    assert normalizar("orden_compra", "") is None


def test_comparar_campo_por_campo():
    verdad = dict(tipo="factura", ruc_emisor="20123456789", ruc_receptor=None, serie="F001", numero=7,
                  fecha_emision=date(2026, 9, 3), moneda="PEN", base_imponible=10.0, igv=1.8,
                  total=11.8, orden_compra=None)
    leido = Comprobante(**{**verdad, "numero": 1, "total": 11.80})
    ok = comparar(leido, verdad)
    assert set(ok) == set(CAMPOS)
    assert not ok["numero"] and ok["total"] and ok["ruc_receptor"]
