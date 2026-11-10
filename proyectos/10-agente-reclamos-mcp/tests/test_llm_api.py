"""
Prueba ModeloLLM y JuezLLM con el SDK real, sin salir a internet:
se intercepta el HTTP y se revisa el request que se habría enviado.
"""

import json

import pytest

openai = pytest.importorskip("openai")

try:  # según la versión, el SDK usa httpx o httpx2
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    httpx = pytest.importorskip("httpx")

from conftest import caso  # noqa: E402
from reclamos.agente import AgenteReclamos  # noqa: E402
from reclamos.juez import JuezLLM  # noqa: E402
from reclamos.llm import ModeloLLM, llamadas_en_texto  # noqa: E402


def _respuesta(texto, llamadas=()):
    mensaje = {"role": "assistant", "content": texto}
    if llamadas:
        mensaje["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                                 for i, n, a in llamadas]
    return {"id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "modelo-test",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if llamadas else "stop", "message": mensaje}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}}


def _cliente(guion, enviados):
    def manejar(request):
        assert request.url.host == "llm.local"
        enviados.append(json.loads(request.content))
        if len(enviados) > len(guion):
            raise AssertionError(json.dumps(enviados[-1]["messages"][-3:], ensure_ascii=False)[:1500])
        return httpx.Response(200, json=guion[len(enviados) - 1])
    return openai.OpenAI(api_key="sk-test", base_url="http://llm.local/v1",
                         http_client=httpx.Client(transport=httpx.MockTransport(manejar)))


def test_loop_completo_con_el_sdk(sistemas, con, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    v = caso(con, "NOT tiene_inyeccion AND caso = 'fraude_reportado' AND r.texto LIKE '%DNI%'")
    idr, idc = int(v["id_reclamo"]), int(v["id_cliente"])
    guion = [
        _respuesta("Reviso al cliente.", [("call_1", "ver_cliente", {"id_cliente": idc})]),
        _respuesta(None, [("call_2", "derivar_reclamo", {"id_reclamo": idr, "area": "Prevención de fraude",
                                                          "resumen": "Consumo no reconocido"})]),
        # algunos servidores locales devuelven la llamada dentro del texto
        _respuesta('<tool_call>\n{"name": "registrar_respuesta", "arguments": {"id_reclamo": %d, '
                   '"resultado": "derivado", "mensaje": "Hola, derivamos su caso a Prevención de fraude, que le '
                   'responderá dentro de 15 días hábiles."}}\n</tool_call>' % idr),
    ]
    enviados = []
    modelo = ModeloLLM("modelo-test")
    modelo.cliente = _cliente(guion, enviados)

    res = AgenteReclamos(modelo, sistemas).atender(idr)

    assert res.accion == "ESCALAR_FRAUDE" and res.resultado_declarado == "derivado"
    assert res.tokens_entrada == 2700
    primero, segundo, _ = enviados
    assert primero["messages"][0]["role"] == "system"
    nombres = {t["function"]["name"] for t in primero["tools"]}
    assert "emitir_abono" in nombres and "bloquear_tarjeta" not in nombres
    # el texto del reclamo llegó enmascarado
    assert "[DNI]" in primero["messages"][1]["content"]
    asistente, resultado = segundo["messages"][-2:]
    assert asistente["tool_calls"][0]["id"] == "call_1" and asistente["content"] == "Reviso al cliente."
    assert resultado["role"] == "tool" and resultado["tool_call_id"] == "call_1"


def test_juez_llm_con_el_sdk(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    enviados = []
    juez = JuezLLM("juez-test")
    juez.cliente = _cliente([_respuesta('{"falla": ["trato"], "aprueba": false}')], enviados)
    v = juez.evaluar("Hola, no procede. Debió leer las condiciones.", "NO_PROCEDE", 0.0)
    assert not v.aprueba and v.falla == ["trato"] and v.tokens == 940
    assert enviados[0]["response_format"] == {"type": "json_object"}
    assert "no procede" in enviados[0]["messages"][1]["content"]


def test_llamadas_en_texto_con_llaves_dobles():
    texto = 'Voy a revisar.\n<tool_call>\n{{"name": "ver_cliente", "arguments": {"id_cliente": 5}}}\n</tool_call>'
    (ll,) = llamadas_en_texto(texto)
    assert ll.nombre == "ver_cliente" and ll.entrada == {"id_cliente": 5}


def test_sin_clave_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        ModeloLLM()


def test_modo_herramientas_en_texto():
    from reclamos.llm import a_texto

    mensajes = [
        {"role": "user", "content": "Reclamo"},
        {"role": "assistant", "content": "Reviso.", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "ver_cliente", "arguments": '{"id_cliente": 5}'}},
            {"id": "b", "type": "function", "function": {"name": "listar_pagos", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": '{"nombre": "Rosa"}'},
        {"role": "tool", "tool_call_id": "b", "content": '{"pagos": []}'},
    ]
    u, a, r = a_texto(mensajes)
    assert a["role"] == "assistant" and a["content"].count("<tool_call>") == 2 and "tool_calls" not in a
    assert r["role"] == "user" and r["content"].count("<tool_response>") == 2
