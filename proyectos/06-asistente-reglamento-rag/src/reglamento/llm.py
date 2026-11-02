"""
Redacción de la respuesta a partir de los artículos recuperados.

El asistente habla con cualquier objeto que implemente `redactar()`:
  - ModeloLLM: cualquier API compatible con chat completions (OpenAI, Groq,
    Together, Ollama, vLLM...). Se cambia con LLM_BASE_URL y LLM_MODELO.
  - ModeloExtractivo: sin API key. Devuelve el artículo mejor ubicado tal cual,
    con su cita. No redacta ni razona, pero nunca dice algo que no esté escrito.
  - ModeloGuionado: respuestas fijas, para tests.

El modelo recibe los artículos numerados [1]..[k] y contesta en JSON con la
respuesta, los números que cita y si los artículos no alcanzan para responder.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol

from .corpus import Fragmento

MODELO_DEFECTO = "gpt-4.1-mini"

SISTEMA = """Eres el asistente de Registros Académicos de la Universidad Qhapaq Ñan.
Respondes preguntas de estudiantes usando SOLO los artículos que se te entregan, numerados [1], [2], ...

Reglas:
- Si los artículos no responden la pregunta, marca "sin_respuesta": true y no adivines.
- Cada plazo, monto o porcentaje que menciones debe estar escrito en un artículo que cites.
- Cita los números de los artículos que usaste en "citas".
- Si un artículo fue modificado por una resolución, ya te llega la versión vigente; no menciones versiones anteriores.
- Responde en español, tuteando, en una a tres oraciones. Nombra el reglamento y el artículo.

Devuelve solo un JSON: {"respuesta": "...", "citas": [1], "sin_respuesta": false}"""


@dataclass
class Redaccion:
    texto: str
    citas: list[int] = field(default_factory=list)     # posiciones 1..k en la lista entregada
    sin_respuesta: bool = False
    tokens_entrada: int = 0
    tokens_salida: int = 0


class Modelo(Protocol):
    nombre: str

    def redactar(self, pregunta: str, fragmentos: list[Fragmento]) -> Redaccion:
        ...


def contexto(fragmentos: list[Fragmento]) -> str:
    return "\n\n".join(f"[{i}] {f.titulo_documento} ({f.cita}) — Artículo {f.articulo}. {f.titulo}.\n{f.texto}"
                       for i, f in enumerate(fragmentos, 1))


def interpretar(contenido: str) -> Redaccion:
    """Lee el JSON del modelo; tolera texto alrededor o un bloque ```json."""
    m = re.search(r"\{.*\}", contenido or "", re.DOTALL)
    try:
        datos = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        datos = {}
    if not datos:
        return Redaccion(texto=(contenido or "").strip(), citas=[], sin_respuesta=False)
    citas = [int(c) for c in datos.get("citas", []) if str(c).strip("[] ").isdigit()]
    return Redaccion(str(datos.get("respuesta", "")).strip(), citas, bool(datos.get("sin_respuesta", False)))


class ModeloLLM:
    def __init__(self, modelo: str | None = None, max_tokens: int = 400):
        from openai import OpenAI  # import diferido: el modo extractivo no necesita el SDK

        clave = os.getenv("LLM_API_KEY")
        if not clave:
            raise RuntimeError("Falta LLM_API_KEY. Cópiala en un archivo .env o usa --demo.")
        self.cliente = OpenAI(api_key=clave, base_url=os.getenv("LLM_BASE_URL") or None)
        self.nombre = modelo or os.getenv("LLM_MODELO", MODELO_DEFECTO)
        self.max_tokens = max_tokens

    def redactar(self, pregunta, fragmentos) -> Redaccion:
        r = self.cliente.chat.completions.create(
            model=self.nombre,
            max_tokens=self.max_tokens,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SISTEMA},
                {"role": "user", "content": f"Artículos:\n\n{contexto(fragmentos)}\n\nPregunta: {pregunta}"},
            ],
        )
        red = interpretar(r.choices[0].message.content or "")
        if r.usage:
            red.tokens_entrada, red.tokens_salida = r.usage.prompt_tokens, r.usage.completion_tokens
        return red


class ModeloExtractivo:
    """Modo demo: el artículo mejor ubicado, recortado a dos oraciones."""

    nombre = "extractivo (sin LLM)"

    def redactar(self, pregunta, fragmentos) -> Redaccion:
        if not fragmentos:
            return Redaccion("", [], sin_respuesta=True)
        f = fragmentos[0]
        oraciones = re.split(r"(?<=[.;])\s+(?=[A-ZÁÉÍÓÚ])", f.texto)
        extracto = " ".join(oraciones[:2])
        return Redaccion(f"Según el {f.titulo_documento} ({f.cita}): {extracto}", [1])


class ModeloGuionado:
    """Devuelve redacciones predefinidas en orden. Para tests."""

    nombre = "guionado"

    def __init__(self, redacciones: list[Redaccion]):
        self.redacciones = list(redacciones)
        self.recibido: list[tuple[str, list[str]]] = []

    def redactar(self, pregunta, fragmentos) -> Redaccion:
        self.recibido.append((pregunta, [f.id for f in fragmentos]))
        return self.redacciones.pop(0)
