import json
from pathlib import Path

from text2sql.agente import AgenteTextToSQL
from text2sql.evaluacion import resultados_equivalentes
from text2sql.llm import LlamadaHerramienta as Llamada
from text2sql.llm import ModeloDemo, ModeloGuionado, RespuestaModelo

CASOS = json.loads((Path(__file__).parents[1] / "evals" / "casos.json").read_text(encoding="utf-8"))


def test_el_agente_se_corrige_cuando_el_sql_falla(db):
    modelo = ModeloGuionado([
        RespuestaModelo("Pruebo.", [Llamada("1", "ejecutar_sql", {"sql": "SELECT total FROM ventas"})]),
        RespuestaModelo("Corrijo.", [Llamada("2", "ejecutar_sql", {"sql": "SELECT COUNT(*) AS n FROM tiendas"})]),
        RespuestaModelo("", [Llamada("3", "responder", {"respuesta": "Hay 24 tiendas.", "sql": "SELECT COUNT(*) AS n FROM tiendas"})]),
    ])
    res = AgenteTextToSQL(modelo, db).preguntar("¿Cuántas tiendas hay?")

    assert res.ok
    assert res.consultas_fallidas == 1
    assert res.filas == [(24,)]
    # el error de la primera consulta le llegó al modelo como mensaje `tool`
    ultimo = modelo.mensajes_recibidos[1][-1]
    assert ultimo["role"] == "tool" and ultimo["tool_call_id"] == "1"
    assert ultimo["content"].startswith("ERROR") and "total" in ultimo["content"]


def test_cada_llamada_recibe_su_resultado(db):
    modelo = ModeloGuionado([
        RespuestaModelo("", [Llamada("a", "listar_tablas", {}),
                             Llamada("b", "describir_tabla", {"tabla": "tiendas"})]),
        RespuestaModelo("", [Llamada("c", "responder", {"respuesta": "ok", "sql": ""})]),
    ])
    AgenteTextToSQL(modelo, db).preguntar("x")
    asistente, *resultados = modelo.mensajes_recibidos[1][-3:]
    assert [t["id"] for t in asistente["tool_calls"]] == ["a", "b"]
    assert [(r["role"], r["tool_call_id"]) for r in resultados] == [("tool", "a"), ("tool", "b")]


def test_sql_bloqueado_no_llega_a_la_base(db):
    modelo = ModeloGuionado([
        RespuestaModelo("", [Llamada("1", "ejecutar_sql", {"sql": "DROP TABLE ventas"})]),
        RespuestaModelo("", [Llamada("2", "responder", {"respuesta": "No puedo.", "sql": ""})]),
    ])
    res = AgenteTextToSQL(modelo, db).preguntar("borra todo")
    assert res.pasos[0].error and "SELECT" in res.pasos[0].salida
    assert db.ejecutar("SELECT COUNT(*) FROM ventas").filas[0][0] > 0


def test_respuesta_en_texto_sin_usar_responder(db):
    modelo = ModeloGuionado([
        RespuestaModelo("", [Llamada("1", "ejecutar_sql", {"sql": "SELECT COUNT(*) FROM tiendas"})]),
        RespuestaModelo("Son 24 tiendas."),
    ])
    res = AgenteTextToSQL(modelo, db).preguntar("¿Cuántas tiendas?")
    assert res.respuesta == "Son 24 tiendas."
    assert res.filas == [(24,)]


def test_limite_de_pasos(db):
    vueltas = [RespuestaModelo("", [Llamada(str(i), "listar_tablas", {})]) for i in range(5)]
    res = AgenteTextToSQL(ModeloGuionado(vueltas), db, max_pasos=3).preguntar("x")
    assert not res.ok and "límite de pasos" in res.respuesta


def test_demo_resuelve_todo_el_set_de_evaluacion(db):
    agente = AgenteTextToSQL(ModeloDemo(), db)
    for caso in CASOS:
        res = agente.preguntar(caso["pregunta"])
        ref = db.ejecutar(caso["sql"])
        assert ref.ok, caso["id"]
        assert res.ok, caso["id"]
        assert resultados_equivalentes(res.filas, ref.filas), caso["id"]


def test_demo_no_inventa_respuestas(db):
    res = AgenteTextToSQL(ModeloDemo(), db).preguntar("¿Quién ganó el Mundial 2022?")
    assert not res.ok and "modo demo" in res.respuesta
