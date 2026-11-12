"""El motor local contra casos chicos armados a mano, donde el resultado se sabe de memoria."""

import pandas as pd
import pytest

from semantico.dax import ErrorDAX
from semantico.motor import Motor
from semantico.tmdl import modelo_desde_textos

TMDL = {
    "tables/Dim.tmdl": (
        "table Dim\n"
        "\tmeasure Filas = COUNTROWS ( Hecho )\n"
        "\tmeasure Total = SUM ( Hecho[monto] )\n"
        "\tmeasure 'Total A' = CALCULATE ( [Total], Hecho[tipo] = \"a\" )\n"
        "\tmeasure 'Total A mantiene' = CALCULATE ( [Total], KEEPFILTERS ( Hecho[tipo] = \"a\" ) )\n"
        "\tmeasure 'Total sin grupo' = CALCULATE ( [Total], REMOVEFILTERS ( Dim ) )\n"
        "\tmeasure Cociente = DIVIDE ( [Total], [Filas] - 2 )\n"
        "\tmeasure Barra = [Total] / ( [Filas] - 2 )\n"
        "\tmeasure 'Grupos chicos' = COUNTROWS ( FILTER ( Dim, [Total] < 15 ) )\n"
        "\tmeasure 'Suma por grupo' = SUMX ( Dim, [Total] * 2 )\n"
        "\tmeasure 'Blanco más uno' = BLANK () + 1\n"
        "\tmeasure Raro = PATHCONTAINS ( \"a\", \"b\" )\n"
        "\tcolumn id\n\t\tdataType: int64\n\t\tisKey\n"
        "\tcolumn grupo\n\t\tdataType: string\n"
        "\tcolumn region\n\t\tdataType: string\n"
        "\tpartition Dim = m\n\t\tsource = RutaDatos & \"/dim.parquet\"\n"
    ),
    "tables/Hecho.tmdl": (
        "table Hecho\n"
        "\tcolumn id_dim\n\t\tdataType: int64\n"
        "\tcolumn tipo\n\t\tdataType: string\n"
        "\tcolumn monto\n\t\tdataType: int64\n"
        "\tpartition Hecho = m\n\t\tsource = RutaDatos & \"/hecho.parquet\"\n"
    ),
    "relationships.tmdl": "relationship r\n\tfromColumn: Hecho.id_dim\n\ttoColumn: Dim.id\n",
}


@pytest.fixture(scope="module")
def chico():
    modelo = modelo_desde_textos(TMDL)
    dim = pd.DataFrame({"id": [1, 2, 3, 4], "grupo": ["x", "y", "z", "w"],
                        "region": ["norte", "norte", "sur", "sur"]})
    hecho = pd.DataFrame({"id_dim": [1, 1, 2, 3, 3, 3], "tipo": ["a", "b", "a", "a", "b", "b"],
                          "monto": [10, 5, 20, 1, 2, 3]})
    return Motor(modelo, {"Dim": dim, "Hecho": hecho})


def test_agrupa_y_omite_blancos(chico):
    # el grupo w no tiene filas: su total es BLANK y no aparece, como en un visual
    assert chico.evaluar("Total", por="Dim[grupo]") == {"x": 15, "y": 20, "z": 6}
    assert chico.evaluar("Total") == {None: 41}


def test_calculate_reemplaza_y_keepfilters_intersecta(chico):
    f = {"Hecho[tipo]": "b"}
    assert chico.evaluar("Total A", f) == {None: 31}       # el filtro "b" se reemplaza por "a"
    assert chico.evaluar("Total A mantiene", f) == {}      # "a" y "b" a la vez: nada


def test_comparacion_de_texto_sin_mayusculas(chico):
    assert chico.evaluar("Total", {"Hecho[tipo]": "A"}) == {None: 31}


def test_removefilters_quita_solo_esa_tabla(chico):
    r = chico.evaluar("Total sin grupo", {"Hecho[tipo]": "a"}, por="Dim[grupo]")
    assert r == {"x": 31, "y": 31, "z": 31, "w": 31}


def test_divide_y_barra_con_cero(chico):
    # grupo x: 2 filas -> denominador 0
    assert "x" not in chico.evaluar("Cociente", por="Dim[grupo]")
    assert chico.evaluar("Barra", por="Dim[grupo]")["x"] == float("inf")


def test_filter_con_transicion_de_contexto(chico):
    # BLANK < 15 es verdadero en DAX: el grupo w (sin filas) también cuenta
    assert chico.evaluar("Grupos chicos") == {None: 2}
    assert chico.evaluar("Grupos chicos", {"Dim[region]": "sur"}) == {None: 2}
    assert chico.evaluar("Suma por grupo", {"Dim[region]": "norte"}) == {None: 70}


def test_blank_mas_uno(chico):
    assert chico.evaluar("Blanco más uno") == {None: 1}


def test_funcion_no_soportada_falla(chico):
    with pytest.raises(ErrorDAX, match="PATHCONTAINS"):
        chico.evaluar("Raro")


def test_medida_o_columna_inexistente(chico):
    with pytest.raises(ErrorDAX):
        chico.evaluar("No existe")
    with pytest.raises(ErrorDAX):
        chico.evaluar("Total", por="Dim[nada]")


def test_motor_real_por_sede(motor):
    r = motor.evaluar("Alumnos matriculados", {"Periodo[periodo]": "2026-2"}, "Sede[sede]")
    assert set(r) == {"Lima Norte", "Lima Centro", "Arequipa"}
    total = motor.evaluar("Alumnos matriculados", {"Periodo[periodo]": "2026-2"})[None]
    assert sum(r.values()) == total  # cada alumno estudia en una sola sede
