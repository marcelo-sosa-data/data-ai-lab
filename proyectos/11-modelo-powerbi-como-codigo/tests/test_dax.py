import pytest

from semantico.dax import (Binaria, Bloque, Columna, En, ErrorDAX, Funcion, Medida, Tabla, Variable, parsear,
                           referencias)


def test_precedencia():
    a = parsear("1 + 2 * 3 > 4 && TRUE")
    assert isinstance(a, Binaria) and a.op == "&&"
    comp = a.izq
    assert comp.op == ">" and comp.izq.op == "+" and comp.izq.der.op == "*"


def test_referencias_y_nombres_con_comillas():
    a = parsear("CALCULATE ( [Alumnos matriculados], 'Tabla X'[col y] = \"a\"\"b\", REMOVEFILTERS ( Sede ) )")
    assert isinstance(a, Funcion) and a.nombre == "CALCULATE"
    assert a.args[0] == Medida("Alumnos matriculados")
    assert a.args[1].izq == Columna("Tabla X", "col y")
    assert a.args[1].der.valor == 'a"b'
    assert a.args[2].args[0] == Tabla("Sede")
    cols, meds, tabs = referencias(a)
    assert cols == {Columna("Tabla X", "col y")} and meds == {"Alumnos matriculados"} and tabs == {"Sede"}


def test_var_return_e_in():
    a = parsear("VAR x = 2 VAR y = x * 3 RETURN IF ( T[c] IN { \"a\", \"b\" }, y )")
    assert isinstance(a, Bloque) and [v for v, _ in a.variables] == ["X", "Y"]
    assert a.variables[1][1].izq == Variable("X")
    assert isinstance(a.retorno.args[0], En)


def test_comentarios_y_not():
    a = parsear("-- comentario\nNOT ISBLANK ( [m] ) // otro")
    assert a == Funcion("NOT", (Funcion("ISBLANK", (Medida("m"),)),))


@pytest.mark.parametrize("texto", ["SUM ( T[c] ", "1 +", "CALCULATE ( [m] ) )", "T[c] ="])
def test_errores_de_sintaxis(texto):
    with pytest.raises(ErrorDAX):
        parsear(texto)
