from datetime import date
from decimal import Decimal

from text2sql.evaluacion import resultados_equivalentes as eq


def test_mismo_resultado_otro_orden_de_filas():
    assert eq([("Lima", 10), ("Piura", 3)], [("Piura", 3), ("Lima", 10)])


def test_columnas_en_otro_orden():
    assert eq([(10, "Lima")], [("Lima", 10)])


def test_columnas_extra_no_penalizan():
    agente = [("La Esquina SJL", 444480.93, 5021)]
    ref = [("La Esquina SJL", Decimal("444480.93"))]
    assert eq(agente, ref)


def test_tolerancia_por_redondeo():
    assert eq([(42.97,)], [(43.0,)])
    assert not eq([(41.5,)], [(43.0,)])


def test_fechas_y_timestamps():
    from datetime import datetime
    assert eq([(datetime(2026, 1, 1),)], [(date(2026, 1, 1),)])


def test_distinto_numero_de_filas():
    assert not eq([("a", 1)], [("a", 1), ("b", 2)])


def test_falta_una_columna():
    assert not eq([("Lima",)], [("Lima", 10)])


def test_valores_cruzados_no_engañan():
    # cada columna tiene los mismos valores, pero las filas no coinciden
    assert not eq([("Lima", 3), ("Piura", 10)], [("Lima", 10), ("Piura", 3)])


def test_resultados_vacios():
    assert eq([], [])
