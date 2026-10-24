"""
Prueba ModeloLLM con el SDK real, pero sin salir a internet:
se intercepta el HTTP y se revisa el request que se habría enviado.
"""

import json

import pytest

openai = pytest.importorskip("openai")

# según la versión, el SDK usa httpx o httpx2
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    httpx = pytest.importorskip("httpx")

from text2sql.agente import AgenteTextToSQL  # noqa: E402
from text2sql.llm import ModeloLLM  # noqa: E402


def _respuesta(texto, llamadas):
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "modelo-test",
        "choices": [{
            "index": 0, "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": texto, "tool_calls": [
                {"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                for i, n, a in llamadas
            ]},
        }],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 80, "total_tokens": 1280},
    }


def test_loop_completo_con_el_sdk(db, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.local/v1")
    sql = "SELECT COUNT(*) AS n FROM tiendas"
    guion = [
        _respuesta("Cuento las tiendas.", [("call_1", "ejecutar_sql", {"sql": sql})]),
        _respuesta(None, [("call_2", "responder", {"respuesta": "La cadena tiene 24 tiendas.", "sql": sql})]),
    ]
    enviados = []

    def manejar(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "llm.local"
        enviados.append(json.loads(request.content))
        return httpx.Response(200, json=guion[len(enviados) - 1])

    modelo = ModeloLLM("modelo-test")
    modelo.cliente = openai.OpenAI(
        api_key="sk-test", base_url="http://llm.local/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(manejar)),
    )

    res = AgenteTextToSQL(modelo, db).preguntar("¿Cuántas tiendas hay?")

    assert res.ok and res.filas == [(24,)]
    assert res.tokens_entrada == 2400 and res.tokens_salida == 160

    primero, segundo = enviados
    assert primero["model"] == "modelo-test"
    assert primero["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in primero["tools"]} == {
        "listar_tablas", "describir_tabla", "ejecutar_sql", "responder"}

    # el segundo request lleva la llamada del asistente y su resultado
    asistente, resultado = segundo["messages"][-2:]
    assert asistente["tool_calls"][0]["id"] == "call_1"
    assert resultado["role"] == "tool" and resultado["tool_call_id"] == "call_1"
    assert '"filas": [[24]]' in resultado["content"]


def test_sin_clave_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        ModeloLLM()
