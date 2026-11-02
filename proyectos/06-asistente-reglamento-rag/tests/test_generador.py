import json
import random
import sys
from collections import Counter

from reglamento.corpus import cargar_corpus
from reglamento.texto import normalizar

sys.path.insert(0, "datos")
from generar_corpus import SIN_RESPUESTA, generar, parametros  # noqa: E402


def test_reproducible_con_la_misma_semilla(tmp_path, rutas):
    otra = generar(tmp_path, seed=7)
    for ruta in rutas["corpus"].glob("*.md"):
        assert (otra["corpus"] / ruta.name).read_text(encoding="utf-8") == ruta.read_text(encoding="utf-8")
    assert otra["preguntas"].read_text(encoding="utf-8") == rutas["preguntas"].read_text(encoding="utf-8")


def test_otra_semilla_cambia_las_cifras():
    distintos = {json.dumps(parametros(random.Random(s)), sort_keys=True) for s in range(5)}
    assert len(distintos) > 1


def test_cada_pregunta_apunta_a_un_articulo_que_existe(preguntas, por_id):
    for q in preguntas:
        assert all(g in por_id for g in q["gold"]), q
        if q["derogado"]:
            assert por_id[q["derogado"]].vigente_hasta is not None


def test_el_dato_esperado_esta_en_el_articulo(preguntas, por_id):
    for q in preguntas:
        if q["gold"]:
            assert normalizar(q["dato"]) in normalizar(por_id[q["gold"][0]].texto), q


def test_composicion_del_set(preguntas):
    tipos = Counter(q["tipo"] for q in preguntas)
    assert tipos["sin_respuesta"] == len(SIN_RESPUESTA)
    assert tipos["vigencia"] == 10 and tipos["nuevo"] == 2
    assert {q["registro"] for q in preguntas} == {"formal", "coloquial"}
    # desarrollo y prueba se reparten cada tipo casi a la mitad
    for tipo in tipos:
        n = Counter(q["split"] for q in preguntas if q["tipo"] == tipo)
        assert abs(n["desarrollo"] - n["prueba"]) <= 1


def test_el_corpus_trae_ruido_de_pdf(rutas):
    crudo = "".join(r.read_text(encoding="utf-8") for r in rutas["corpus"].glob("*.md"))
    assert "Secretaría General | Pág." in crudo
    assert any(linea.endswith("-") for linea in crudo.splitlines())
    assert len(cargar_corpus(rutas["corpus"])) == 72
