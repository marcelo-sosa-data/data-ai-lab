"""Cliente de executeQueries con el HTTP interceptado: se revisa lo que se envía y cómo se lee la respuesta."""

import json

import httpx
import pytest

from semantico.pruebas import Caso
from semantico.servicio import ClienteServicio, consulta_dax

CASO = Caso(id="x", medida="Alumnos matriculados", sql="", filtros={"Periodo[periodo]": "2026-2"},
            por="Sede[sede]")


def test_consulta_dax():
    q = consulta_dax(CASO)
    assert q.startswith("EVALUATE\nSUMMARIZECOLUMNS (")
    assert "'Sede'[sede]" in q
    assert 'TREATAS ( { "2026-2" }, \'Periodo\'[periodo] )' in q
    assert '"valor", [Alumnos matriculados]' in q
    q2 = consulta_dax(Caso(id="y", medida="m", sql="", filtros={"Matricula[retiro_total]": [True]}))
    assert "TREATAS ( { TRUE }, 'Matricula'[retiro_total] )" in q2


def test_cliente_envia_y_lee(monkeypatch):
    vistos = []

    def responder(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        filas = [{"Sede[sede]": "Lima Norte", "[valor]": 3604}, {"Sede[sede]": "Arequipa", "[valor]": 1580},
                 {"Sede[sede]": "Lima Centro", "[valor]": None}]
        return httpx.Response(200, json={"results": [{"tables": [{"rows": filas}]}]})

    http = httpx.Client(transport=httpx.MockTransport(responder))
    r = ClienteServicio("ds-1", "tok", http).evaluar(CASO)
    assert r == {"Lima Norte": 3604, "Arequipa": 1580}
    req = vistos[0]
    assert str(req.url) == "https://api.powerbi.com/v1.0/myorg/datasets/ds-1/executeQueries"
    assert req.headers["Authorization"] == "Bearer tok"
    cuerpo = json.loads(req.content)
    assert cuerpo["queries"][0]["query"] == consulta_dax(CASO)


def test_cliente_reporta_errores():
    def responder(request):
        return httpx.Response(200, json={"results": [{"error": {"code": "DAXError", "message": "x"}}]})

    cliente = ClienteServicio("ds", "t", httpx.Client(transport=httpx.MockTransport(responder)))
    with pytest.raises(RuntimeError, match="DAXError"):
        cliente.evaluar(CASO)
    cliente = ClienteServicio("ds", "t", httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(401, text="no autorizado"))))
    with pytest.raises(RuntimeError, match="401"):
        cliente.evaluar(CASO)


def test_refrescar_espera_a_que_termine():
    estados = iter(["Unknown", "Unknown", "Completed"])
    pedidos = []

    def responder(request):
        pedidos.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(202)
        return httpx.Response(200, json={"value": [{"status": next(estados)}]})

    cliente = ClienteServicio("ds", "t", httpx.Client(transport=httpx.MockTransport(responder)))
    esperas = []
    assert cliente.refrescar("ws", intervalo=5, dormir=esperas.append) == "Completed"
    assert pedidos[0] == ("POST", "/v1.0/myorg/groups/ws/datasets/ds/refreshes")
    assert esperas == [5, 5]


def test_refresco_fallido():
    def responder(request):
        if request.method == "POST":
            return httpx.Response(202)
        return httpx.Response(200, json={"value": [{"status": "Failed"}]})

    cliente = ClienteServicio("ds", "t", httpx.Client(transport=httpx.MockTransport(responder)))
    with pytest.raises(RuntimeError, match="Failed"):
        cliente.refrescar("ws", dormir=lambda s: None)
