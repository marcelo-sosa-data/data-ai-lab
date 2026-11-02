from reglamento.texto import expandir, normalizar, terminos


def test_normalizar_quita_tildes_y_conserva_ene():
    assert normalizar("¿Cuántos AÑOS dura? Matrícula.") == "cuantos años dura matricula"


def test_expandir_agrega_termino_del_reglamento_sin_borrar():
    q = expandir(normalizar("Si jalo un curso por trica"))
    assert q.startswith("si jalo un curso por trica")
    assert "desaprobar" in q and "asignatura" in q and "tercera matricula" in q


def test_expandir_no_toca_texto_formal():
    texto = normalizar("plazo para la rectificación de notas")
    assert expandir(texto) == texto


def test_terminos_sin_stopwords_y_con_raiz():
    t = terminos("¿Cuántos créditos puedo llevar en el semestre?")
    assert "puedo" not in t and "el" not in t
    assert terminos("créditos") == terminos("crédito")


def test_sinonimos_solo_si_se_piden():
    assert "desaprob" not in " ".join(terminos("jale calculo"))
    assert any(x.startswith("desaprob") for x in terminos("jale calculo", con_sinonimos=True))
