from datetime import date

from reglamento.asistente import MENSAJE_SIN_RESPUESTA, Asistente
from reglamento.llm import ModeloExtractivo, ModeloGuionado, Redaccion
from reglamento.recuperador import CONFIGURACIONES

HOY = date(2026, 9, 1)
LEXICO = CONFIGURACIONES["bm25+sinonimos"]
Q = "¿Hasta qué semana puedo retirarme de una asignatura?"


def test_baja_confianza_no_llama_al_modelo(recuperador):
    modelo = ModeloGuionado([])                  # si lo llamara, fallaría por lista vacía
    r = Asistente(recuperador, modelo, umbral=1e9, config=LEXICO).preguntar(Q, HOY)
    assert r.abstencion == "confianza" and r.texto == MENSAJE_SIN_RESPUESTA
    assert modelo.recibido == []


def test_respuesta_con_citas_validas(recuperador):
    modelo = ModeloGuionado([Redaccion("Hasta la semana 8.", [1], tokens_entrada=900, tokens_salida=30)])
    r = Asistente(recuperador, modelo, umbral=0, config=LEXICO).preguntar(Q, HOY)
    assert r.respondio and r.citas[0].id == "RE-2024/art-10@2026-03-01"
    assert r.tokens_entrada == 900
    assert modelo.recibido[0][1][0] == "RE-2024/art-10@2026-03-01"   # el modelo recibe la versión vigente


def test_citas_fuera_de_rango_se_descartan(recuperador):
    modelo = ModeloGuionado([Redaccion("Hasta la semana 8.", [1, 9, 1])])
    r = Asistente(recuperador, modelo, umbral=0, k=5, config=LEXICO).preguntar(Q, HOY)
    assert [f.id for f in r.citas] == ["RE-2024/art-10@2026-03-01"]
    assert r.citas_descartadas == [9]


def test_sin_citas_no_hay_respuesta(recuperador):
    modelo = ModeloGuionado([Redaccion("Creo que hasta la semana 12.", [7])])
    r = Asistente(recuperador, modelo, umbral=0, k=5, config=LEXICO).preguntar(Q, HOY)
    assert r.abstencion == "sin_citas" and r.citas == [] and r.citas_descartadas == [7]


def test_el_modelo_puede_decir_que_no_alcanza(recuperador):
    modelo = ModeloGuionado([Redaccion("", [], sin_respuesta=True)])
    r = Asistente(recuperador, modelo, umbral=0, config=LEXICO).preguntar("hay wifi en el campus?", HOY)
    assert r.abstencion == "modelo" and not r.respondio


def test_modo_extractivo_cita_el_primer_articulo(recuperador):
    r = Asistente(recuperador, ModeloExtractivo(), umbral=0, config=LEXICO).preguntar(Q, HOY)
    assert r.respondio and "semana 8" in r.texto
    assert r.texto.startswith("Según el Reglamento de Estudios de Pregrado (RE-2024, art. 10 (mod. RCU-014-2026))")
