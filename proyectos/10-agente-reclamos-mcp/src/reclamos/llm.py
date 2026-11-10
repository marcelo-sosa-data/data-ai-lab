"""
Capa delgada sobre el modelo de lenguaje, igual que en el proyecto 01.

El agente habla con cualquier objeto que implemente `completar()`:
  - ModeloLLM: cualquier API compatible con chat completions (OpenAI, Groq,
    Together, Ollama, vLLM, llama.cpp) cambiando LLM_BASE_URL y LLM_MODELO
  - ModeloDemo: flujo fijo sin API key, para ver el proceso completo
  - ModeloGuionado: respuestas en orden, para testear el loop
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .guardrails import detectar_inyeccion
from .prompts import leer_reclamo
from .regla_actual import BACKOFFICE, CONTRACARGOS, FRAUDE, OPERACIONES, derivar, normalizar


@dataclass
class LlamadaHerramienta:
    id: str
    nombre: str
    entrada: dict


@dataclass
class RespuestaModelo:
    texto: str = ""
    herramientas: list[LlamadaHerramienta] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_salida: int = 0

    def como_mensaje(self) -> dict:
        """Mensaje de asistente en formato chat completions."""
        # contenido vacío y no None: algunos servidores compatibles rechazan null
        mensaje: dict = {"role": "assistant", "content": self.texto or ""}
        if self.herramientas:
            mensaje["tool_calls"] = [
                {"id": h.id, "type": "function",
                 "function": {"name": h.nombre, "arguments": json.dumps(h.entrada, ensure_ascii=False)}}
                for h in self.herramientas
            ]
        return mensaje


class Modelo(Protocol):
    nombre: str

    def completar(self, sistema: str, mensajes: list[dict], herramientas: list[dict]) -> RespuestaModelo:
        ...


# --------------------------------------------------------------------------

MODELO_DEFECTO = "gpt-4.1-mini"
_LLAMADA_EN_TEXTO = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def llamadas_en_texto(texto: str, prefijo: str = "texto") -> list[LlamadaHerramienta]:
    """
    Algunos servidores locales devuelven la llamada dentro del texto, con el
    formato <tool_call>{...}</tool_call> de la plantilla de Qwen y Hermes.
    """
    llamadas = []
    for i, bloque in enumerate(_LLAMADA_EN_TEXTO.findall(texto or "")):
        try:
            d = json.loads(bloque)
        except json.JSONDecodeError:
            # a veces la plantilla escapa las llaves: {{"name": ...}}
            try:
                d = json.loads(bloque.replace("{{", "{").replace("}}", "}"))
            except json.JSONDecodeError:
                continue
        args = d.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if d.get("name"):
            llamadas.append(LlamadaHerramienta(f"{prefijo}_{i}", d["name"], args))
    return llamadas


def a_texto(mensajes: list[dict]) -> list[dict]:
    """Reescribe llamadas y resultados en el formato de texto de Qwen y Hermes."""
    salida = []
    for m in mensajes:
        if m["role"] == "assistant" and m.get("tool_calls"):
            bloques = [m.get("content") or ""] + [
                "<tool_call>\n" + json.dumps({"name": t["function"]["name"],
                                              "arguments": json.loads(t["function"]["arguments"])},
                                             ensure_ascii=False) + "\n</tool_call>" for t in m["tool_calls"]]
            salida.append({"role": "assistant", "content": "\n".join(b for b in bloques if b)})
        elif m["role"] == "tool":
            texto = f"<tool_response>\n{m['content']}\n</tool_response>"
            if salida and salida[-1]["role"] == "user" and salida[-1]["content"].startswith("<tool_response>"):
                salida[-1]["content"] += "\n" + texto
            else:
                salida.append({"role": "user", "content": texto})
        else:
            salida.append(m)
    return salida


class ModeloLLM:
    """Cliente para cualquier endpoint compatible con la API de chat completions."""

    def __init__(self, modelo: str | None = None, max_tokens: int = 1024):
        from openai import OpenAI  # import diferido: la demo no necesita el SDK

        clave = os.getenv("LLM_API_KEY")
        if not clave:
            raise RuntimeError("Falta LLM_API_KEY. Cópiala en un archivo .env o usa --demo.")
        self.cliente = OpenAI(api_key=clave, base_url=os.getenv("LLM_BASE_URL") or None)
        self.nombre = modelo or os.getenv("LLM_MODELO", MODELO_DEFECTO)
        self.max_tokens = max_tokens
        self._vueltas = 0
        # para servidores locales cuya plantilla no muestra los mensajes `tool` (llama.cpp con Qwen, por ejemplo)
        self.herramientas_en_texto = os.getenv("LLM_HERRAMIENTAS_EN_TEXTO", "") == "1"

    def completar(self, sistema, mensajes, herramientas) -> RespuestaModelo:
        r = self.cliente.chat.completions.create(
            model=self.nombre,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[{"role": "system", "content": sistema},
                      *(a_texto(mensajes) if self.herramientas_en_texto else mensajes)],
            tools=herramientas,
        )
        msg = r.choices[0].message
        llamadas = []
        for t in msg.tool_calls or []:
            try:
                entrada = json.loads(t.function.arguments or "{}")
            except json.JSONDecodeError:
                entrada = {}
            llamadas.append(LlamadaHerramienta(t.id, t.function.name, entrada))
        texto = msg.content or ""
        self._vueltas += 1
        if not llamadas:
            llamadas = llamadas_en_texto(texto, f"call_t{self._vueltas}")
            if llamadas:
                texto = _LLAMADA_EN_TEXTO.sub("", texto).strip()
        uso = r.usage
        return RespuestaModelo(texto, llamadas, uso.prompt_tokens if uso else 0,
                               uso.completion_tokens if uso else 0)


# --------------------------------------------------------------------------

def _historial(mensajes: list[dict]) -> list[tuple[str, dict, dict | None]]:
    """(herramienta, entrada, salida) de cada llamada ya hecha. Salida None si fue error."""
    pedidas = {}
    for m in mensajes:
        for t in m.get("tool_calls") or []:
            pedidas[t["id"]] = (t["function"]["name"], json.loads(t["function"]["arguments"]))
    hechas = []
    for m in mensajes:
        if m["role"] == "tool" and m["tool_call_id"] in pedidas:
            nombre, entrada = pedidas[m["tool_call_id"]]
            try:
                salida = None if m["content"].startswith("ERROR") else json.loads(m["content"])
            except json.JSONDecodeError:
                salida = None
            hechas.append((nombre, entrada, salida))
    return hechas


def _montos(texto: str) -> list[float]:
    pares = re.findall(r"(\d+(?:[.,]\d{1,2})?)\s*soles?|s/\s*(\d+(?:[.,]\d{1,2})?)", normalizar(texto))
    return [float(v.replace(",", ".")) for par in pares for v in par if v]


def _candidato(movs: list[dict], texto: str, tipos: set[str]) -> dict | None:
    """El movimiento que más se parece a lo que describe el cliente: comercio y monto."""
    t, montos = normalizar(texto), _montos(texto)
    mejor, puntaje = None, -1.0
    for m in movs:
        if m["tipo"] not in tipos:
            continue
        p = 0.0
        if normalizar(m["comercio"]) in t:
            p += 2
        if any(abs(m["monto"] - x) <= max(1.0, 0.02 * x) for x in montos):
            p += 2
        if p > puntaje:  # la lista viene del más reciente al más antiguo: en empate gana el reciente
            mejor, puntaje = m, p
    return mejor


class ModeloDemo:
    """
    Flujo fijo sin LLM: la intención sale de la misma macro de palabras que usa
    hoy la primera línea (regla_actual), pero antes de decidir se verifica en
    los sistemas por MCP. Sirve para ver el proceso TO BE sin API key y como
    línea base: lo que mejora frente al AS IS se debe a verificar con datos,
    no a entender mejor el texto.
    """

    nombre = "demo (macro + verificación)"

    def __init__(self):
        self._n = 0

    def _llamar(self, nombre: str, texto: str = "", **entrada) -> RespuestaModelo:
        self._n += 1
        return RespuestaModelo(texto, [LlamadaHerramienta(f"demo_{self._n}", nombre, entrada)])

    def completar(self, sistema, mensajes, herramientas) -> RespuestaModelo:
        r = leer_reclamo(mensajes[0]["content"])
        disponibles = {h["function"]["name"] for h in herramientas}
        hechas = _historial(mensajes)
        nombres = [h[0] for h in hechas]
        idr, idc, texto = r["id_reclamo"], r["id_cliente"], r["texto"]
        fecha = datetime.strptime(r["fecha_hora"][:10], "%Y-%m-%d")
        desde, hasta = (fecha - timedelta(days=60)).strftime("%Y-%m-%d"), fecha.strftime("%Y-%m-%d")
        t = normalizar(texto)
        area = derivar(texto)
        es_recarga = "recarga" in t or "saldo" in t

        # se termina cuando ya se registró la respuesta
        if "registrar_respuesta" in nombres and hechas[-1][2] is not None:
            return RespuestaModelo("Reclamo atendido.")

        derivacion = next((e for n, e, s in hechas if n == "derivar_reclamo" and s), None)
        abono = next((s["abono_registrado"] for n, e, s in hechas if n == "emitir_abono" and s), None)
        if derivacion:
            return self._llamar("registrar_respuesta", **_cierre(r, "derivado", area=derivacion["area"],
                                                                      resumen=derivacion["resumen"]))
        if abono:
            return self._llamar("registrar_respuesta", **_cierre(r, "procede_abonado", abono=abono,
                                                                  hechos=_ultimo(hechas, "revisar_cargo")))
        if "ver_cliente" not in nombres:
            return self._llamar("ver_cliente", "Reviso al cliente y su tarjeta.", id_cliente=idc)

        if detectar_inyeccion(texto) or "emitir_abono" not in disponibles:
            return self._derivar(idr, "Supervisor de reclamos",
                                 "El texto trae instrucciones para el asistente. Requiere revisión humana.")

        if area == OPERACIONES and not es_recarga:
            pagos = _ultimo(hechas, "listar_pagos")
            if pagos is None:
                inicio = (fecha - timedelta(days=20)).strftime("%Y-%m-%d")
                return self._llamar("listar_pagos", "Busco el pago.", id_cliente=idc, desde=inicio, hasta=hasta)
            colgado = next((p for p in pagos["pagos"] if not p["aplicado"]), None)
            if colgado:
                return self._derivar(idr, OPERACIONES, f"Pago {colgado['id_pago']} del {colgado['fecha_hora']} por "
                                     f"S/ {colgado['monto']:.2f} vía {colgado['canal_pago']} figura sin aplicar.")
            return self._llamar("registrar_respuesta", **_cierre(r, "no_procede", pagos=pagos["pagos"]))

        if area in (FRAUDE, CONTRACARGOS):
            return self._derivar(idr, area, f"Derivado por el tipo de reclamo. Texto: {texto[:200]}")

        movs = _ultimo(hechas, "listar_movimientos")
        if movs is None:
            return self._llamar("listar_movimientos", "Busco el movimiento que menciona.", id_cliente=idc,
                                desde=desde, hasta=hasta)
        if es_recarga:
            tipos, motivo = {"recarga"}, "recarga_no_acreditada"
        elif "membres" in t or "mantenimiento" in t:
            tipos, motivo = {"membresia"}, "membresia_exonerada"
        else:
            tipos, motivo = {"compra"}, "cargo_duplicado"
        cand = _candidato(movs["movimientos"], texto, tipos)
        if cand is None:
            return self._derivar(idr, "Supervisor de reclamos", "No ubiqué el movimiento que menciona el cliente.")
        hechos = _ultimo(hechas, "revisar_cargo")
        if hechos is None:
            return self._llamar("revisar_cargo", "Reviso el cargo.", id_movimiento=cand["id_movimiento"])

        if "emitir_abono" in nombres:  # el servidor rechazó el abono
            return self._derivar(idr, "Supervisor de reclamos",
                                 f"Abono de S/ {hechos['monto']:.2f} rechazado por el sistema; requiere revisión.")
        if _procede(hechos, motivo):
            return self._llamar("emitir_abono", "Los datos sustentan el abono.", id_reclamo=idr,
                                id_movimiento=hechos["id_movimiento"], monto=hechos["monto"], motivo=motivo)
        return self._llamar("registrar_respuesta", **_cierre(r, "no_procede", hechos=hechos))

    def _derivar(self, idr: int, area: str, resumen: str) -> RespuestaModelo:
        return self._llamar("derivar_reclamo", "Derivo el reclamo.", id_reclamo=idr, area=area, resumen=resumen)


def _ultimo(hechas, nombre):
    return next((s for n, e, s in reversed(hechas) if n == nombre and s is not None), None)


def _procede(h: dict, motivo: str) -> bool:
    if motivo == "recarga_no_acreditada":
        return h.get("recarga", {}).get("estado_operador") == "fallida"
    if motivo == "membresia_exonerada":
        return bool(h.get("cargo_dentro_de_exoneracion"))
    gemelos = [c for c in h.get("otros_cargos_mismo_comercio_48h", [])
               if c["mismo_monto"] and c["minutos_de_diferencia"] <= 10]
    return h["estado"] == "liquidado" and any(c["estado"] == "liquidado" for c in gemelos)


PLAZO = "El área le responderá dentro de los 15 días hábiles contados desde su reclamo."


def _cierre(r: dict, resultado: str, **d) -> dict:
    """Mensaje al cliente según lo verificado."""
    cod = r["codigo"]
    if resultado == "derivado":
        msg = (f"Hola, sobre su reclamo {cod}: revisamos su caso y lo derivamos a {d['area']}, que es el área "
               f"que puede resolverlo. {PLAZO}")
    elif resultado == "procede_abonado":
        a, h = d["abono"], d["hechos"]
        msg = (f"Hola, sobre su reclamo {cod}: verificamos el cargo de {h['comercio']} del {h['fecha_hora'][:10]} "
               f"por S/ {a['monto']:.2f} y corresponde la devolución. Hemos abonado S/ {a['monto']:.2f} a su "
               "tarjeta; lo verá en sus movimientos en las próximas 48 horas.")
    elif "pagos" in d:
        aplicados = [p for p in d["pagos"] if p["aplicado"]]
        if aplicados:
            p = aplicados[0]
            msg = (f"Hola, sobre su reclamo {cod}: su pago de S/ {p['monto']:.2f} del {p['fecha_hora'][:10]} se "
                   f"aplicó a su deuda el {p['fecha_aplicacion'][:10]}. Puede que la app aún mostrara el saldo "
                   "anterior cuando lo revisó. Si ve una diferencia, responda a este mensaje con su constancia.")
        else:
            msg = (f"Hola, sobre su reclamo {cod}: no encontramos pagos recientes a su tarjeta. Si pagó, responda "
                   "a este mensaje con la constancia para ubicarlo.")
        resultado = "no_procede"
    else:
        h = d["hechos"]
        base = f"Hola, sobre su reclamo {cod}: revisamos el cargo de {h['comercio']} del {h['fecha_hora'][:10]} por S/ {h['monto']:.2f}. "
        if "recarga" in h:
            msg = base + (f"El operador {h['recarga']['operador']} confirmó que la recarga se acreditó, por eso no "
                          "corresponde una devolución. Si no ve el saldo, le sugerimos consultarlo con su operador.")
        elif h["tipo"] == "membresia":
            msg = base + (f"Su exoneración de membresía estuvo vigente hasta el {h['membresia_exonerada_hasta']}, y "
                          "este cargo es posterior, por eso no procede la devolución.")
        elif any(c["estado"] == "revertido" for c in h.get("otros_cargos_mismo_comercio_48h", [])):
            msg = base + ("El segundo cargo que vio ya fue revertido por el comercio, así que solo se le cobró una "
                          "vez. No corresponde una devolución adicional.")
        else:
            msg = base + ("No encontramos otro cargo igual en ese comercio en los minutos cercanos; los cargos que "
                          "figuran son compras distintas. Por eso no procede la devolución.")
    return {"id_reclamo": r["id_reclamo"], "resultado": resultado, "mensaje": msg}


# --------------------------------------------------------------------------

class ModeloGuionado:
    """Devuelve respuestas predefinidas en orden. Para tests."""

    nombre = "guionado"

    def __init__(self, respuestas: list[RespuestaModelo]):
        self.respuestas = list(respuestas)
        self.mensajes_recibidos: list[list[dict]] = []

    def completar(self, sistema, mensajes, herramientas) -> RespuestaModelo:
        self.mensajes_recibidos.append([dict(m) for m in mensajes])
        return self.respuestas.pop(0)
