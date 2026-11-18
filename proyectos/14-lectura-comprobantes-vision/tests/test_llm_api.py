"""
Prueba ExtractorLLM con el SDK real, pero sin salir a internet:
se intercepta el HTTP y se revisa el request que se habría enviado.
"""

import base64
import json
from datetime import date

import pytest
from PIL import Image

openai = pytest.importorskip("openai")

# según la versión, el SDK usa httpx o httpx2
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    httpx = pytest.importorskip("httpx")

from comprobantes.llm import ExtractorLLM  # noqa: E402


def _respuesta(contenido: str) -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "vision-test",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": contenido}}],
        "usage": {"prompt_tokens": 1450, "completion_tokens": 210, "total_tokens": 1660},
    }


LEIDO = {"tipo": "factura", "ruc_emisor": "20693392340", "ruc_receptor": "20967823202", "serie": "F001",
         "numero": 17609, "fecha_emision": "2026-10-15", "moneda": "PEN", "base_imponible": 2857.49,
         "igv": 514.35, "total": 3371.84, "orden_compra": "OC-2026-01206",
         "items": [{"descripcion": "Gaseosa 3 L pack x4", "cantidad": 100, "valor_unitario": 20.72,
                    "importe": 2072.0}]}


def _extractor(monkeypatch, respuestas, enviados):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    def manejar(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "llm.local"
        enviados.append(json.loads(request.content))
        return httpx.Response(200, json=_respuesta(respuestas[len(enviados) - 1]))

    ext = ExtractorLLM("vision-test")
    ext.cliente = openai.OpenAI(api_key="sk-test", base_url="http://llm.local/v1",
                                http_client=httpx.Client(transport=httpx.MockTransport(manejar)))
    return ext


def test_request_con_imagen_y_salida_estructurada(monkeypatch, tmp_path):
    ruta = tmp_path / "f.jpg"
    Image.new("RGB", (2400, 3400), "white").save(ruta)
    enviados = []
    ext = _extractor(monkeypatch, [json.dumps(LEIDO)], enviados)

    lec = ext.extraer(ruta)

    c = lec.comprobante
    assert (c.serie, c.numero, c.total, c.fecha_emision) == ("F001", 17609, 3371.84, date(2026, 10, 15))
    assert c.items[0].importe == 2072.0
    assert lec.confianza == {} and lec.extractor == "vision-test"
    assert (ext.tokens_entrada, ext.tokens_salida) == (1450, 210)

    req = enviados[0]
    assert req["model"] == "vision-test" and req["temperature"] == 0
    assert req["messages"][0]["role"] == "system"
    partes = req["messages"][1]["content"]
    imagen = next(p for p in partes if p["type"] == "image_url")["image_url"]["url"]
    assert imagen.startswith("data:image/jpeg;base64,")
    # la imagen se reduce antes de mandarla: el lado mayor queda en 1600 px
    from io import BytesIO
    assert max(Image.open(BytesIO(base64.b64decode(imagen.split(",")[1]))).size) == 1600
    formato = req["response_format"]
    assert formato["type"] == "json_schema" and formato["json_schema"]["strict"] is True
    assert formato["json_schema"]["schema"]["additionalProperties"] is False


def test_respuesta_invalida_queda_vacia_y_va_a_revision(monkeypatch, tmp_path):
    ruta = tmp_path / "f.jpg"
    Image.new("RGB", (100, 100), "white").save(ruta)
    ext = _extractor(monkeypatch, ["esto no es json"], [])
    lec = ext.extraer(ruta)
    assert lec.comprobante.total is None and lec.comprobante.ruc_emisor is None


def test_sin_clave_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        ExtractorLLM()
