from datetime import date

import pandas as pd
import pytest

from reglamento.asistente import Asistente
from reglamento.evaluacion import (calibrar_umbral, contiene_dato, evaluar_abstencion, evaluar_busqueda,
                                   evaluar_respuestas, resumen_busqueda, resumen_respuestas, separacion)
from reglamento.llm import ModeloExtractivo
from reglamento.recuperador import CONFIGURACIONES

LEXICO = CONFIGURACIONES["bm25+sinonimos"]


def _df(confianzas, con_respuesta, posiciones=None):
    return pd.DataFrame({"id": range(len(confianzas)), "pregunta": [f"p{i}" for i in range(len(confianzas))],
                         "config": "x", "confianza": confianzas, "con_respuesta": con_respuesta,
                         "posicion": posiciones or [1] * len(confianzas)})


def test_resumen_busqueda_ignora_las_sin_respuesta():
    df = _df([0.9, 0.8, 0.7, 0.1], [True, True, True, False], [1, 2, None, None])
    r = resumen_busqueda(df).iloc[0]
    assert r["n"] == 3
    assert r["acierto@1"] == pytest.approx(1 / 3) and r["acierto@5"] == pytest.approx(2 / 3)
    assert r["mrr"] == pytest.approx((1 + 0.5 + 0) / 3)


def test_umbral_deja_pasar_la_cobertura_pedida():
    df = _df([i / 100 for i in range(1, 101)], [True] * 100)
    u = calibrar_umbral(df, cobertura=0.9)
    assert (df["confianza"] >= u).mean() == pytest.approx(0.9, abs=0.011)


def test_abstencion_cuenta_bien():
    df = _df([0.9, 0.85, 0.5, 0.95, 0.4], [True, True, True, False, False])
    a = evaluar_abstencion(df, 0.8)
    assert (a["validas_respondidas"], a["validas"]) == (2, 3)
    assert (a["sin_respuesta_abstenidas"], a["sin_respuesta"]) == (1, 2)
    assert a["ajenas_que_pasan"] == ["p3"]


def test_separacion_es_un_auc():
    assert separacion(_df([0.9, 0.8, 0.2, 0.1], [True, True, False, False])) == 1.0
    assert separacion(_df([0.5, 0.5], [True, False])) == 0.5


def test_evaluar_busqueda_por_pregunta(recuperador, preguntas):
    df = evaluar_busqueda(recuperador, preguntas, LEXICO, date(2026, 9, 1))
    assert len(df) == len(preguntas)
    assert df.loc[~df["con_respuesta"], "posicion"].isna().all()
    assert not df["error_version"].any()          # con filtro de vigencia no hay errores de versión
    assert resumen_busqueda(df).iloc[0]["acierto@5"] > 0.8


def test_sin_vigencia_aparecen_errores_de_version(recuperador, preguntas):
    from reglamento.recuperador import Configuracion

    sin = Configuracion("sin", vectorial=False, vigencia=False)
    df = evaluar_busqueda(recuperador, [q for q in preguntas if q["tipo"] == "vigencia"], sin)
    assert df["error_version"].any()


def test_evaluar_respuestas_extractivas(recuperador, preguntas):
    muestra = [q for q in preguntas if q["tipo"] in ("vigencia", "sin_respuesta")][:8]
    asistente = Asistente(recuperador, ModeloExtractivo(), umbral=0, config=LEXICO)
    df = evaluar_respuestas(asistente, muestra)
    r = resumen_respuestas(df)
    assert r["validas"] + r["sin_respuesta"] == len(muestra)
    assert df.loc[df["cita_correcta"], "respondio"].all()


def test_contiene_dato_respeta_signos():
    assert contiene_dato("El parcial no puede pesar más de 30% ...", "30%")
    assert not contiene_dato("la constancia cuesta S/ 30", "30%")
    assert contiene_dato("La nota mínima aprobatoria es ONCE (11).", "once (11)")
    assert not contiene_dato("cualquier texto", "")
