from datetime import date

import numpy as np
import pytest

from reglamento.recuperador import CONFIGURACIONES, Configuracion, Recuperador, _rangos

HOY = date(2026, 9, 1)
ANTES = date(2025, 10, 1)
LEXICO = CONFIGURACIONES["bm25+sinonimos"]


def test_rangos_solo_entre_candidatos():
    r = _rangos(np.array([0.1, 0.9, 0.5, 0.7]), np.array([True, False, True, True]))
    assert list(r[[0, 2, 3]]) == [3, 2, 1] and np.isinf(r[1])


def test_encuentra_el_articulo_formal(recuperador):
    b = recuperador.buscar("plazo para solicitar la rectificación de una calificación", HOY, 5, LEXICO)
    assert b.ids[0] == "RE-2024/art-16"


def test_sinonimos_rescatan_la_jerga(recuperador):
    q = "quiero congelar un ciclo para chambear, por cuanto tiempo puedo?"
    sin = recuperador.buscar(q, HOY, 5, CONFIGURACIONES["bm25"]).ids
    con = recuperador.buscar(q, HOY, 5, LEXICO).ids
    assert sin[0] != "RE-2024/art-12" and con[0] == "RE-2024/art-12"


def test_la_fecha_decide_la_version(recuperador):
    q = "¿Hasta qué semana puedo retirarme de una asignatura?"
    hoy = recuperador.buscar(q, HOY, 5, LEXICO).ids
    antes = recuperador.buscar(q, ANTES, 5, LEXICO).ids
    assert hoy[0] == "RE-2024/art-10@2026-03-01" and "RE-2024/art-10" not in hoy
    assert antes[0] == "RE-2024/art-10" and "RE-2024/art-10@2026-03-01" not in antes


def test_sin_filtro_compiten_las_dos_versiones(recuperador):
    q = "¿Hasta qué semana puedo retirarme de una asignatura?"
    sin_filtro = Configuracion("x", vectorial=False, vigencia=False)
    ids = recuperador.buscar(q, HOY, 5, sin_filtro).ids
    assert {"RE-2024/art-10", "RE-2024/art-10@2026-03-01"} <= set(ids[:2])


def test_articulo_incorporado_no_existe_antes(recuperador):
    ids = recuperador.buscar("puedo usar chatgpt para hacer mis trabajos?", ANTES, 10, LEXICO).ids
    assert "RE-2024/art-35-A@2026-03-01" not in ids


def test_hibrido_y_vectorial_devuelven_k_vigentes(recuperador):
    for nombre in ("hibrido rrf", "vectorial"):
        b = recuperador.buscar("cuanto cuesta un certificado de estudios", HOY, 5, CONFIGURACIONES[nombre])
        assert len(b.ids) == 5 and all(r.fragmento.vigente(HOY) for r in b.resultados)
        assert -1 <= b.confianza <= 1 and b.resultados[0].coseno is not None


def test_peso_vectorial_1_equivale_a_solo_vectores(recuperador):
    q = "si pago tarde la cuota cuanto me cobran de mas?"
    a = recuperador.buscar(q, HOY, 5, Configuracion("a", peso_vectorial=1.0)).ids
    b = recuperador.buscar(q, HOY, 5, CONFIGURACIONES["vectorial"]).ids
    assert a == b


def test_configuracion_vectorial_sin_codificador_falla(fragmentos):
    with pytest.raises(ValueError, match="codificador"):
        Recuperador(fragmentos).buscar("algo", HOY, 5, CONFIGURACIONES["vectorial"])


def test_precodificar_reutiliza_vectores(recuperador):
    recuperador.precodificar(["pregunta repetida", "pregunta repetida"])
    v = recuperador._consultas["pregunta repetida"]
    recuperador.precodificar(["pregunta repetida"])
    assert recuperador._consultas["pregunta repetida"] is v


def test_cache_de_vectores_en_disco(fragmentos, tmp_path):
    from reglamento.embeddings import CodificadorHash

    ruta = tmp_path / "v.npz"
    a = Recuperador(fragmentos, CodificadorHash(), ruta).vectores
    assert ruta.exists()
    b = Recuperador(fragmentos, CodificadorHash(), ruta).vectores
    assert np.allclose(a, b)
