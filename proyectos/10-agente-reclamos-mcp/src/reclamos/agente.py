"""
Host del agente: conecta al servidor MCP, filtra herramientas por perfil,
corre el loop del modelo y deja la traza de cada llamada.

Lo que cuenta como resultado es lo que quedó escrito en los sistemas (abonos,
derivaciones, respuesta), no lo que el modelo dice que hizo.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from mcp import Client

from .guardrails import datos_personales, detectar_inyeccion, revisar_mensaje
from .llm import Modelo
from .permisos import PERFILES, Control
from .prompts import SISTEMA, primer_mensaje
from .regla_actual import BACKOFFICE, CONTRACARGOS, FRAUDE, OPERACIONES
from .servidor import SUPERVISOR, Sistemas, crear_servidor

ACCION_POR_AREA = {
    FRAUDE: "ESCALAR_FRAUDE",
    OPERACIONES: "ESCALAR_OPERACIONES",
    CONTRACARGOS: "ESCALAR_CONTRACARGOS",
    SUPERVISOR: "ESCALAR_SUPERVISOR",
    BACKOFFICE: "ESCALAR_BACKOFFICE",
}


@dataclass
class Paso:
    herramienta: str
    entrada: dict
    salida: str
    error: bool
    permitido: bool = True
    razon: str = ""
    pensamiento: str = ""


@dataclass
class Resultado:
    id_reclamo: int
    codigo: str = ""
    perfil: str = ""
    accion: str = ""
    resultado_declarado: str = ""
    mensaje: str = ""
    monto_abonado: float = 0.0
    id_movimiento_abonado: int | None = None
    pasos: list[Paso] = field(default_factory=list)
    alertas_inyeccion: list[str] = field(default_factory=list)
    salidas_rechazadas: int = 0
    pii_al_modelo: int = 0
    cerrado_por_host: bool = False
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos: float = 0.0

    @property
    def denegadas(self) -> int:
        return sum(1 for p in self.pasos if not p.permitido)


def _a_herramienta(t) -> dict:
    """Herramienta MCP al formato `tools` de chat completions."""
    return {"name": t.name, "description": t.description or "", "parameters": t.input_schema}


def _texto(resultado) -> str:
    return "\n".join(getattr(c, "text", "") for c in resultado.content)


class AgenteReclamos:
    def __init__(self, modelo: Modelo, sistemas: Sistemas, max_pasos: int = 12):
        self.modelo = modelo
        self.sistemas = sistemas
        self.servidor = crear_servidor(sistemas)
        self.max_pasos = max_pasos

    # ------------------------------------------------------------ API pública

    def atender(self, id_reclamo: int) -> Resultado:
        return self.atender_lote([id_reclamo])[0]

    def atender_lote(self, ids: list[int], al_terminar=None) -> list[Resultado]:
        """Atiende varios reclamos con una sola conexión MCP."""
        return asyncio.run(self._lote(ids, al_terminar))

    async def _lote(self, ids, al_terminar) -> list[Resultado]:
        resultados = []
        async with Client(self.servidor) as cliente:
            herramientas = [_a_herramienta(t) for t in (await cliente.list_tools()).tools]
            for i, idr in enumerate(ids, 1):
                res = await self._atender(cliente, herramientas, idr)
                resultados.append(res)
                if al_terminar:
                    al_terminar(i, res)
        return resultados

    # ------------------------------------------------------------ un reclamo

    async def _atender(self, cliente: Client, catalogo: list[dict], id_reclamo: int) -> Resultado:
        inicio = time.perf_counter()
        res = Resultado(id_reclamo=id_reclamo)

        r = await cliente.call_tool("ver_reclamo", {"id_reclamo": id_reclamo})
        if r.is_error:
            raise ValueError(_texto(r))
        reclamo = json.loads(_texto(r))
        res.codigo = reclamo["codigo"]
        res.alertas_inyeccion = detectar_inyeccion(reclamo["texto"])
        perfil = PERFILES["revision_humana" if res.alertas_inyeccion else "asistente_reclamos"]
        res.perfil = perfil.nombre
        control = Control(perfil, id_reclamo, reclamo["id_cliente"])
        herramientas = [{"type": "function", "function": h} for h in control.visibles(catalogo)]

        mensajes: list[dict] = [{"role": "user", "content": primer_mensaje(reclamo, perfil.nombre,
                                                                         res.alertas_inyeccion)}]
        cerrado = False
        for _ in range(self.max_pasos):
            m = self.modelo.completar(SISTEMA, mensajes, herramientas)
            res.tokens_entrada += m.tokens_entrada
            res.tokens_salida += m.tokens_salida
            mensajes.append(m.como_mensaje())
            if not m.herramientas:
                if cerrado:
                    break
                mensajes.append({"role": "user", "content": "Falta cerrar la atención con registrar_respuesta."})
                continue
            for h in m.herramientas:
                salida, error, paso = await self._ejecutar(cliente, control, h, res, m.texto.strip())
                res.pasos.append(paso)
                mensajes.append({"role": "tool", "tool_call_id": h.id, "content": salida})
                cerrado = cerrado or (h.nombre == "registrar_respuesta" and not error)
            if cerrado:
                break

        if not cerrado:
            await self._cerrar_por_host(cliente, reclamo, res)

        res.pii_al_modelo = sum(len(datos_personales(str(x.get("content") or ""))) for x in mensajes)
        self._resumir(res)
        res.segundos = time.perf_counter() - inicio
        return res

    async def _ejecutar(self, cliente, control: Control, h, res: Resultado, pensamiento: str):
        d = control.autorizar(h.nombre, h.entrada)
        if not d.permitido:
            return f"ERROR: permiso denegado. {d.razon}", True, Paso(h.nombre, h.entrada, d.razon, True, False,
                                                                     d.razon, pensamiento)
        if h.nombre == "registrar_respuesta":
            abonos = [a["monto"] for a in self.sistemas.ops.del_reclamo(control.id_reclamo)["abonos"]]
            rev = revisar_mensaje(str(h.entrada.get("mensaje", "")), abonos, str(h.entrada.get("resultado", "")))
            if not rev.ok:
                res.salidas_rechazadas += 1
                motivo = " ".join(rev.problemas)
                return (f"ERROR: el mensaje no pasó la revisión de salida. {motivo} Corrígelo y vuelve a "
                        "registrar.", True, Paso(h.nombre, h.entrada, motivo, True, True, "revisión de salida",
                                                 pensamiento))
        r = await cliente.call_tool(h.nombre, h.entrada)
        texto = _texto(r)
        if r.is_error:
            return f"ERROR: {texto}", True, Paso(h.nombre, h.entrada, texto, True, True, "", pensamiento)
        try:
            control.registrar_salida(h.nombre, json.loads(texto), False)
        except json.JSONDecodeError:
            pass
        return texto, False, Paso(h.nombre, h.entrada, texto, False, True, "", pensamiento)

    async def _cerrar_por_host(self, cliente, reclamo: dict, res: Resultado) -> None:
        """Si el agente no cierra, el reclamo no se pierde: va a la cola del supervisor."""
        idr = reclamo["id_reclamo"]
        propio = self.sistemas.ops.del_reclamo(idr)
        if propio["respuesta"]:
            return
        res.cerrado_por_host = True
        if not propio["derivaciones"] and not propio["abonos"]:
            await cliente.call_tool("derivar_reclamo", {"id_reclamo": idr, "area": SUPERVISOR,
                                                         "resumen": "El asistente no cerró la atención."})
        resultado = "procede_abonado" if propio["abonos"] else "derivado"
        await cliente.call_tool("registrar_respuesta", {
            "id_reclamo": idr, "resultado": resultado,
            "mensaje": (f"Hola, recibimos su reclamo {reclamo['codigo']}. Lo está revisando un especialista, que le "
                        "responderá dentro de los 15 días hábiles contados desde su reclamo.")})

    def _resumir(self, res: Resultado) -> None:
        propio = self.sistemas.ops.del_reclamo(res.id_reclamo)
        if propio["abonos"]:
            a = propio["abonos"][0]
            res.accion, res.monto_abonado, res.id_movimiento_abonado = "ABONAR", a["monto"], a["id_movimiento"]
        elif propio["derivaciones"]:
            res.accion = ACCION_POR_AREA[propio["derivaciones"][-1]["area"]]
        else:
            res.accion = "NO_PROCEDE"
        if propio["respuesta"]:
            res.resultado_declarado = propio["respuesta"]["resultado"]
            res.mensaje = propio["respuesta"]["mensaje"]
