"""
Prueba ModeloLLM con el SDK real, pero sin salir a internet:
se intercepta el HTTP y se revisa el request que se habría enviado.
"""

import json
from datetime import date

import pytest

openai = pytest.importorskip("openai")

# según la versión, el SDK usa httpx o httpx2
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    httpx = pytest.importorskip("httpx")

from reglamento.asistente import Asistente  # noqa: E402
from reglamento.llm import ModeloLLM, interpretar  # noqa: E402
from reglamento.recuperador import CONFIGURACIONES  # noqa: E402


def _respuesta(contenido: str) -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "modelo-test",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": contenido}}],
        "usage": {"prompt_tokens": 1450, "completion_tokens": 62, "total_tokens": 1512},
    }


def test_flujo_completo_con_el_sdk(recuperador, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    enviados = []
    contenido = json.dumps({"respuesta": "Puedes retirarte hasta la semana 8 (RE-2024, art. 10).",
                            "citas": [1], "sin_respuesta": False})

    def manejar(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "llm.local"
        enviados.append(json.loads(request.content))
        return httpx.Response(200, json=_respuesta(contenido))

    modelo = ModeloLLM("modelo-test")
    modelo.cliente = openai.OpenAI(api_key="sk-test", base_url="http://llm.local/v1",
                                   http_client=httpx.Client(transport=httpx.MockTransport(manejar)))
    asistente = Asistente(recuperador, modelo, umbral=0, config=CONFIGURACIONES["bm25+sinonimos"])
    r = asistente.preguntar("¿Hasta qué semana puedo retirarme de una asignatura?", date(2026, 9, 1))

    assert r.respondio and "semana 8" in r.texto
    assert r.citas[0].id == "RE-2024/art-10@2026-03-01"
    assert (r.tokens_entrada, r.tokens_salida) == (1450, 62)

    (req,) = enviados
    assert req["model"] == "modelo-test" and req["temperature"] == 0
    assert req["response_format"] == {"type": "json_object"}
    sistema, usuario = req["messages"]
    assert sistema["role"] == "system" and "SOLO" in sistema["content"]
    assert all(f"[{i}] " in usuario["content"] for i in range(1, 6)) and "[6] " not in usuario["content"]
    assert "[1] Reglamento de Estudios" in usuario["content"]
    assert "semana 10" not in usuario["content"]         # la versión derogada no llega al modelo


def test_interpretar_tolera_bloques_y_basura():
    r = interpretar('Aquí va:\n```json\n{"respuesta": "Sí.", "citas": ["2", 3], "sin_respuesta": false}\n```')
    assert r.texto == "Sí." and r.citas == [2, 3]
    r = interpretar("no es json")
    assert r.texto == "no es json" and r.citas == [] and not r.sin_respuesta


def test_sin_clave_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        ModeloLLM()
