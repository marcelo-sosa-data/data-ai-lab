from semantico.pruebas import comparar, correr, medidas_sin_prueba


def test_todas_las_medidas_pasan(motor, casos, con):
    resultados = correr(motor, casos, con)
    fallas = [(r.caso.id, r.error, r.diferencias[:2]) for r in resultados if not r.ok]
    assert not fallas


def test_cada_medida_tiene_al_menos_un_caso(modelo, casos):
    assert medidas_sin_prueba(modelo.medidas, casos) == []


def test_comparar_reporta_diferencias():
    assert comparar({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0 + 1e-12}) == []
    assert comparar({"a": 1.0}, {"a": 1.1}) == [("a", 1.0, 1.1)]
    assert comparar({"a": 1.0}, {"a": 1.0, "b": 3}) == [("b", None, 3)]
