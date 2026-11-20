import pandas as pd

from admision import normalizar as N


def test_documento_recupera_ceros_y_limpia():
    assert N.documento(2138554) == "02138554"
    assert N.documento(2138554.0) == "02138554"
    assert N.documento(" 4567 8912 ") == "45678912"
    assert N.documento("4.567.891", "DNI") == "04567891"
    assert N.documento(1234567, "CE") == "001234567"
    assert N.documento("ab123456") == "AB123456"
    assert N.documento(None) is None and N.documento("  ") is None


def test_documento_sin_ceros_para_cruzar_con_tesoreria():
    assert N.documento_sin_ceros("02138554") == N.documento_sin_ceros(N.documento(2138554))
    assert N.documento_sin_ceros("001234567") == "1234567"


def test_celular_en_cualquier_formato():
    for v in ("987654321", "+51 987 654 321", "987-654-321", "51987654321", 987654321):
        assert N.celular(v) == "987654321"
    assert N.celular("014567890") is None
    assert N.celular(None) is None


def test_referencia_saca_el_codigo():
    assert N.referencia_codigo(" 2027100123 ") == "2027100123"
    assert N.referencia_codigo("COD 2027100123") == "2027100123"
    assert N.referencia_codigo("20271001234") is None
    assert N.referencia_codigo(None) is None


def test_clave_y_encabezado():
    assert N.clave("  Ingeniería  de Sistemas ") == "INGENIERIA DE SISTEMAS"
    assert N.encabezado("Fecha de registro") == "fecha_de_registro"
    assert N.encabezado("Carrera de interés") == "carrera_de_interes"


def test_mapear_catalogo_lleva_al_nombre_oficial():
    s = N.mapear_catalogo(pd.Series(["EXAMEN DE ADMISION", "Examen de admisión", "CONVENIO"]),
                          ["Examen de admisión"])
    assert list(s) == ["Examen de admisión", "Examen de admisión", "CONVENIO"]


def test_fechas_dia_mes_iso_y_vacias():
    s, problema = N.fechas(pd.Series(["14/05/2026 10:32", "2026-05-15 08:00:00", "", "03/02/2026"]))
    assert problema is None
    assert s[0] == pd.Timestamp("2026-05-14 10:32")
    assert s[1] == pd.Timestamp("2026-05-15 08:00")
    assert pd.isna(s[2])
    assert s[3] == pd.Timestamp("2026-02-03")


def test_fechas_detecta_mes_primero():
    _, problema = N.fechas(pd.Series(["05/14/2026 10:32", "11/30/2026 08:00"]))
    assert problema == "fechas en formato mes/día"


def test_fechas_ilegibles():
    _, problema = N.fechas(pd.Series(["14/05/2026", "mañana"]))
    assert "no se pueden leer" in problema
