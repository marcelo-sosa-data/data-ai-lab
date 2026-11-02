import numpy as np

from reglamento.bm25 import BM25


def test_el_documento_con_el_termino_gana():
    bm = BM25([["mora", "cuota"], ["beca", "promedio"], ["cuota", "matricula"]])
    p = bm.puntajes(["mora"])
    assert p.argmax() == 0 and p[1] == 0


def test_termino_raro_pesa_mas_que_comun():
    bm = BM25([["cuota", "mora"], ["cuota", "beca"], ["cuota", "plazo"]])
    assert bm.idf["mora"] > bm.idf["cuota"] > 0       # idf nunca negativo


def test_consulta_sin_terminos_conocidos():
    bm = BM25([["a", "b"], ["c"]])
    assert np.all(bm.puntajes(["zzz"]) == 0)


def test_documento_corto_gana_a_igual_frecuencia():
    bm = BM25([["mora"] + ["x"] * 20, ["mora", "y"]])
    p = bm.puntajes(["mora"])
    assert p[1] > p[0]
