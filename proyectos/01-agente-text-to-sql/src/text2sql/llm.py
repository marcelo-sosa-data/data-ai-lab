"""
Capa delgada sobre el modelo de lenguaje.

El agente no depende de un proveedor: habla con cualquier objeto que
implemente `completar()`. Así se puede:
  - usar cualquier API compatible con OpenAI (OpenAI, Groq, Together, Ollama,
    vLLM...) cambiando solo LLM_BASE_URL y LLM_MODELO (ModeloLLM)
  - correr una demo sin API key (ModeloDemo)
  - testear el loop del agente con respuestas guionadas (ModeloGuionado)

Los mensajes viajan en el formato de chat completions: el asistente pide
herramientas con `tool_calls` y cada resultado vuelve como un mensaje `tool`.
"""

from __future__ import annotations

import difflib
import json
import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


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
        mensaje: dict = {"role": "assistant", "content": self.texto or None}
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


class ModeloLLM:
    """Cliente para cualquier endpoint compatible con la API de chat completions."""

    def __init__(self, modelo: str | None = None, max_tokens: int = 2048):
        from openai import OpenAI  # import diferido: la demo no necesita el SDK

        clave = os.getenv("LLM_API_KEY")
        if not clave:
            raise RuntimeError("Falta LLM_API_KEY. Cópiala en un archivo .env o usa --demo.")
        self.cliente = OpenAI(api_key=clave, base_url=os.getenv("LLM_BASE_URL") or None)
        self.nombre = modelo or os.getenv("LLM_MODELO", MODELO_DEFECTO)
        self.max_tokens = max_tokens

    def completar(self, sistema, mensajes, herramientas) -> RespuestaModelo:
        r = self.cliente.chat.completions.create(
            model=self.nombre,
            max_tokens=self.max_tokens,
            temperature=0,
            # sistema y herramientas van primero y no cambian entre pasos: los
            # proveedores que cachean prefijos no los cobran completos cada vuelta
            messages=[{"role": "system", "content": sistema}, *mensajes],
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
        uso = r.usage
        return RespuestaModelo(msg.content or "", llamadas,
                               uso.prompt_tokens if uso else 0, uso.completion_tokens if uso else 0)


# --------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in texto).split())


class ModeloDemo:
    """
    Simula al modelo para poder probar todo sin API key.

    No "entiende" la pregunta: la busca en el set de evaluación y usa el SQL
    de referencia. Sirve para ver el flujo completo (herramientas, validación,
    ejecución, interfaz), no para medir calidad.
    """

    nombre = "demo (sin LLM)"

    def __init__(self, ruta_casos: str | Path | None = None):
        ruta = Path(ruta_casos or Path(__file__).parents[2] / "evals" / "casos.json")
        self.casos = json.loads(ruta.read_text(encoding="utf-8"))
        self._n = 0

    def _buscar(self, pregunta: str) -> dict | None:
        objetivo = _normalizar(pregunta)
        mejor, puntaje = None, 0.0
        for caso in self.casos:
            p = difflib.SequenceMatcher(None, objetivo, _normalizar(caso["pregunta"])).ratio()
            if p > puntaje:
                mejor, puntaje = caso, p
        return mejor if puntaje >= 0.75 else None

    def _id(self) -> str:
        self._n += 1
        return f"demo_{self._n}"

    def completar(self, sistema, mensajes, herramientas) -> RespuestaModelo:
        pregunta = mensajes[0]["content"]
        pasos = sum(1 for m in mensajes if m["role"] == "assistant")
        caso = self._buscar(pregunta)

        if caso is None:
            return RespuestaModelo(herramientas=[LlamadaHerramienta(self._id(), "responder", {
                "respuesta": ("En modo demo solo puedo responder las preguntas del set de "
                              "evaluación (evals/casos.json). Configura LLM_API_KEY "
                              "para hacer cualquier pregunta."),
                "sql": "",
            })])

        if pasos == 0:
            return RespuestaModelo(
                texto="Reviso primero qué tablas hay.",
                herramientas=[LlamadaHerramienta(self._id(), "listar_tablas", {})],
            )
        if pasos == 1:
            return RespuestaModelo(
                texto="Armo la consulta.",
                herramientas=[LlamadaHerramienta(self._id(), "ejecutar_sql", {"sql": caso["sql"]})],
            )

        resultado = mensajes[-1]["content"]
        return RespuestaModelo(herramientas=[LlamadaHerramienta(self._id(), "responder", {
            "respuesta": _redactar(resultado, caso),
            "sql": caso["sql"],
        })])


DIAS = {"Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles", "Thursday": "jueves",
        "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"}


def _redactar(contenido: str, caso: dict) -> str:
    """Llena la plantilla del caso con los resultados reales de la consulta."""
    if contenido.startswith("ERROR") or "plantilla_demo" not in caso:
        return _resumir(contenido)
    filas = [[DIAS.get(v, v) if isinstance(v, str) else v for v in f]
             for f in json.loads(contenido)["filas"]]
    lista = "\n".join(caso.get("fila_demo", "").format(*f) for f in filas)
    try:
        return caso["plantilla_demo"].format(f=filas, filas=lista)
    except (IndexError, KeyError, ValueError):
        return _resumir(contenido)


def _resumir(contenido: str) -> str:
    if contenido.startswith("ERROR"):
        return f"No pude obtener el dato: {contenido}"
    datos = json.loads(contenido)
    cols, filas = datos["columnas"], datos["filas"]
    if not filas:
        return "La consulta no devolvió resultados."
    if len(filas) == 1:
        return "Resultado: " + ", ".join(f"{c} = {_fmt(v)}" for c, v in zip(cols, filas[0]))
    top = "; ".join(" | ".join(_fmt(v) for v in f) for f in filas[:3])
    return f"{len(filas)} filas. Primeras: {top}"


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


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
