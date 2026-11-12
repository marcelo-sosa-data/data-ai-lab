import pytest

from semantico.tmdl import ErrorTMDL, archivo_parquet, leer_objetos, modelo_desde_textos


def test_lee_el_modelo(modelo):
    assert set(modelo.tablas) == {"Periodo", "Sede", "Carrera", "Curso", "Alumno", "Matricula", "Seccion",
                                  "Inscripcion"}
    assert len(modelo.medidas) == 18
    assert len(modelo.relaciones) == 10
    assert modelo.parametros["RutaDatos"].endswith("matricula-dev")
    assert modelo.tablas["Seccion"].clave() == "id_seccion"


def test_medida_de_varias_lineas_con_descripcion(modelo):
    m = modelo.medidas["Matriculados año anterior"]
    assert m.expresion.startswith("VAR orden = SELECTEDVALUE ( Periodo[orden] )")
    assert "orden - 2" in m.expresion
    assert m.descripcion.startswith("Matriculados del mismo semestre")
    assert m.formato == "#,0"
    assert m.carpeta == "Comparación anual"


def test_particion_y_parquet(modelo):
    assert archivo_parquet(modelo.tablas["Inscripcion"].particion) == "inscripcion.parquet"
    assert archivo_parquet('Parquet.Document(File.Contents("C:\\datos\\x.parquet"))') == "x.parquet"
    assert archivo_parquet("Sql.Database(\"srv\", \"db\")") is None


def test_indentacion_con_espacios_falla():
    with pytest.raises(ErrorTMDL, match="tabs"):
        leer_objetos("table T\n    column a\n")


def test_relacion_bidireccional_y_nombres_con_comillas():
    textos = {
        "tables/a.tmdl": "table 'Tabla A'\n\tcolumn 'id a'\n\t\tdataType: int64\n\t\tisKey\n",
        "tables/b.tmdl": "table B\n\tcolumn id_a\n\t\tdataType: int64\n",
        "relationships.tmdl": "relationship r1\n\tfromColumn: B.id_a\n\ttoColumn: 'Tabla A'.'id a'\n"
                              "\tcrossFilteringBehavior: bothDirections\n",
    }
    m = modelo_desde_textos(textos)
    r = m.relaciones[0]
    assert (r.tabla_hacia, r.columna_hacia, r.bidireccional) == ("Tabla A", "id a", True)
    assert m.tablas["Tabla A"].columnas["id a"].es_clave
