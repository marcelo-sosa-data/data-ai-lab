from admision.incidencias import INCIDENCIAS, evaluar


def _una(nombre):
    return [i for i in INCIDENCIAS if i.nombre == nombre]


def test_quince_incidencias_con_nombre_unico():
    assert len({i.nombre for i in INCIDENCIAS}) == len(INCIDENCIAS) == 15


def test_resultados_esperados(carpeta):
    casos = {"modalidad_nueva": "bloquea", "crm_duplicado": "absorbe",
             "pruebas_masivas": "absorbe", "admision_incompleta": "bloquea",
             "resultados_revertidos": "publica distinto"}
    df = evaluar(carpeta / "crudo", [i for n in casos for i in _una(n)]).set_index("incidencia")
    for nombre, esperado in casos.items():
        assert df.loc[nombre, "nuevo_resultado"] == esperado, nombre
    assert df.loc["crm_duplicado", "actual_desvio"] == 1.0
    assert "02_modalidad_en_catalogo" in df.loc["modalidad_nueva", "pruebas_con_error"]
