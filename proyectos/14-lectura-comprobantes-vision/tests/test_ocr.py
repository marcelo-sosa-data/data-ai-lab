from datetime import date

import numpy as np
import pytest
from conftest import HAY_TESSERACT

from comprobantes.ocr import Linea, _serie, a_numero, parsear


def lineas(*textos, conf=95.0):
    return [Linea(t, [(p, conf) for p in t.split()]) for t in textos]


def test_a_numero():
    assert a_numero("1,132.50") == 1132.50
    assert a_numero("594,34") == 594.34
    assert a_numero("12.345,60") == 12345.60
    assert a_numero("7.33") == 7.33


@pytest.mark.parametrize("leido, serie", [("F001", "F001"), ("FO01", "F001"), ("FOO0O1", "F001"),
                                          ("FA01", "FA01"), ("FAO01", "FA01"), ("EB01", "EB01"),
                                          ("8001", "B001"), ("FO0O3", "F003")])
def test_serie_con_confusiones_tipicas(leido, serie):
    assert _serie(leido) == serie


def test_parser_formato_comercial():
    c, conf = parsear(lineas(
        "Industrias Nueva Era S.A. R.U.C. 20693392340",
        "Lima - Perú Telf. 01 718-3617 FACTURA ELECTRÓNICA",
        "FO001-00017609",
        "Fecha de emisión : 15/10/2026",
        "Señor(es) : COMERCIAL TAYTA S.A.C.",
        "RUC : 20967823202",
        "Moneda : SOLES",
        "Orden de compra : 0C-2026-01206",
        "Op. Gravada S/ 2,857.49",
        "1.G.V. 18% S/ 514.35",
        "Importe Total S/ 3,371.84",
    ))
    assert (c.tipo, c.ruc_emisor, c.ruc_receptor) == ("factura", "20693392340", "20967823202")
    assert (c.serie, c.numero, c.fecha_emision) == ("F001", 17609, date(2026, 10, 15))
    assert (c.moneda, c.orden_compra) == ("PEN", "OC-2026-01206")
    assert (c.base_imponible, c.igv, c.total) == (2857.49, 514.35, 3371.84)
    assert conf["total"] == pytest.approx(0.95)


def test_parser_ticket_en_dolares_y_fecha_en_texto():
    c, _ = parsear(lineas(
        "QUISPE MAMANI ROSA ELVIRA",
        "RUC: 10452 3456 78",
        "BOLETA DE VENTA ELECTRONICA",
        "EB01-25392",
        "FECHA: 3 de setiembre de 2026 10:22",
        "MONEDA: DOLARES AMERICANOS",
        "OP. GRAVADA US$ 100.00",
        "IGV 18% US$ 18.00",
        "TOTAL US$ 118.00",
    ))
    assert (c.tipo, c.serie, c.numero, c.moneda) == ("boleta", "EB01", 25392, "USD")
    assert c.ruc_emisor == "10452345678" and c.ruc_receptor is None
    assert c.fecha_emision == date(2026, 9, 3)
    assert (c.base_imponible, c.igv, c.total) == (100.0, 18.0, 118.0)


def test_parser_no_inventa_lo_que_no_lee():
    c, conf = parsear(lineas("FACTURA ELECTRONICA F001-123", "Sub Total S/ 100.00", "TOTAL S/ 118.00"))
    assert c.igv is None and "igv" not in conf
    assert c.total == 118.0


@pytest.mark.skipif(not HAY_TESSERACT, reason="sin tesseract instalado")
def test_extraccion_real_de_un_pdf_limpio(tablas, ruta_db):
    from plantillas import PLANTILLAS

    from comprobantes.esquema import CAMPOS, comparar
    from comprobantes.ocr import ExtractorOCR

    v = tablas["aux_verdad"]
    fila = v[(v["captura"] == "pdf") & (v["plantilla"] == "comercial")].iloc[0].to_dict()
    lec = ExtractorOCR().extraer(ruta_db.parent / "imagenes" / fila["archivo"])
    fila["fecha_emision"] = fila["fecha_emision"].date()
    verdad = {k: (None if fila[k] is None or (isinstance(fila[k], float) and np.isnan(fila[k])) else fila[k])
              for k in CAMPOS}
    ok = comparar(lec.comprobante, verdad)
    assert sum(ok.values()) >= len(CAMPOS) - 1, ok
    assert "comercial" in PLANTILLAS
