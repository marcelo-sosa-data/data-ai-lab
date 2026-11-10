"""
Juez de la respuesta al cliente y su calibración contra etiquetas de revisión.

El juez no decide si la acción fue la correcta (eso se mide contra el caso
real); revisa el mensaje frente a lo que quedó registrado: que sea coherente,
que diga qué se revisó, que no prometa lo que no se hizo, que trate bien al
cliente y que, si se derivó, diga a dónde y en qué plazo.

Un juez que aprueba de más infla la calidad que se reporta. Por eso se mide
contra etiquetas de revisión (sensibilidad y especificidad) y con eso se
corrige la tasa de aprobación que da sobre mensajes sin etiquetar.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .guardrails import _ABONO_AFIRMADO, datos_personales
from .llm import MODELO_DEFECTO
from .regla_actual import normalizar

CRITERIOS = {
    "coherente": "El mensaje es coherente con la acción registrada (si hubo abono lo dice; si no procede o se "
                 "derivó, no dice que procede).",
    "sustento": "Si decide (abono o no procede), dice qué se revisó: comercio, fecha, monto, pago u operador.",
    "sin_promesas": "No afirma ni promete devoluciones, abonos o resultados que no están registrados.",
    "trato": "Trata al cliente con respeto y no lo culpa ni lo regaña.",
    "siguiente_paso": "Si se derivó, indica el área y el plazo de respuesta.",
}

INSTRUCCIONES_JUEZ = (
    "Eres revisor de calidad de las respuestas a reclamos de una fintech. Evalúas un mensaje frente a lo que "
    "quedó registrado en los sistemas. Criterios:\n"
    + "\n".join(f"- {k}: {v}" for k, v in CRITERIOS.items())
    + "\nResponde solo con JSON: {\"falla\": [criterios que no cumple], \"aprueba\": true o false}. "
      "Aprueba solo si cumple todos los criterios que aplican."
)


@dataclass
class Veredicto:
    aprueba: bool
    falla: list[str] = field(default_factory=list)
    tokens: int = 0


def describir_registro(accion: str, monto_abonado: float) -> str:
    if accion == "ABONAR":
        return f"Se registró un abono de S/ {monto_abonado:.2f}."
    if accion == "NO_PROCEDE":
        return "Se registró que el reclamo no procede. No hubo abono."
    area = {"ESCALAR_FRAUDE": "Prevención de fraude", "ESCALAR_OPERACIONES": "Operaciones",
            "ESCALAR_CONTRACARGOS": "Contracargos", "ESCALAR_SUPERVISOR": "Supervisor de reclamos",
            "ESCALAR_BACKOFFICE": "Backoffice de tarjetas"}.get(accion, accion)
    return f"Se derivó el reclamo a {area}. No hubo abono."


class JuezReglas:
    """Chequeos que se pueden programar sin modelo. No evalúa el trato."""

    nombre = "reglas"

    def evaluar(self, mensaje: str, accion: str, monto_abonado: float) -> Veredicto:
        t = normalizar(mensaje)
        falla = []
        dice_procede = bool(re.search(r"(?<!no )(procede|corresponde) (la|el|su) (devolucion|abono)", t))
        dice_no_procede = bool(re.search(r"no (procede|corresponde)", t))
        if accion == "ABONAR" and (dice_no_procede or not re.search(r"abon|devol", t)):
            falla.append("coherente")
        if accion != "ABONAR" and dice_procede:
            falla.append("coherente")
        if accion in ("ABONAR", "NO_PROCEDE") and not (re.search(r"s/\s?\d", t) and re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2} de [a-z]+", t)):
            falla.append("sustento")
        if accion != "ABONAR" and _ABONO_AFIRMADO.search(t):
            falla.append("sin_promesas")
        if accion.startswith("ESCALAR") and not re.search(r"\d+ dias habiles", t):
            falla.append("siguiente_paso")
        if datos_personales(mensaje):
            falla.append("sin_promesas")
        return Veredicto(not falla, sorted(set(falla)))


class JuezLLM:
    """Juez con un LLM por chat completions. Usa las mismas variables que el agente."""

    def __init__(self, modelo: str | None = None):
        from openai import OpenAI

        clave = os.getenv("LLM_API_KEY")
        if not clave:
            raise RuntimeError("Falta LLM_API_KEY para el juez LLM; sin clave se usa el juez de reglas.")
        self.cliente = OpenAI(api_key=clave, base_url=os.getenv("LLM_BASE_URL") or None)
        self.nombre = modelo or os.getenv("LLM_MODELO_JUEZ") or os.getenv("LLM_MODELO", MODELO_DEFECTO)

    def evaluar(self, mensaje: str, accion: str, monto_abonado: float) -> Veredicto:
        usuario = f"Registro en sistemas: {describir_registro(accion, monto_abonado)}\n\nMensaje al cliente:\n{mensaje}"
        r = self.cliente.chat.completions.create(
            model=self.nombre, temperature=0, max_tokens=120,
            messages=[{"role": "system", "content": INSTRUCCIONES_JUEZ}, {"role": "user", "content": usuario}],
            response_format={"type": "json_object"},
        )
        return leer_veredicto(r.choices[0].message.content or "", r.usage.total_tokens if r.usage else 0)


def leer_veredicto(texto: str, tokens: int = 0) -> Veredicto:
    """Lee el JSON del juez. Si no se puede leer, cuenta como desaprobado."""
    try:
        d = json.loads(texto[texto.index("{"): texto.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return Veredicto(False, ["ilegible"], tokens)
    falla = [f for f in d.get("falla", []) if f in CRITERIOS]
    aprueba = bool(d.get("aprueba", not falla))
    return Veredicto(aprueba and not falla, falla, tokens)


# ------------------------------------------------------------------ calibración

def matriz(etiqueta: pd.Series, juez: pd.Series) -> dict:
    """Etiqueta y juez: True = aprueba. Sensibilidad = aprueba lo bueno; especificidad = rechaza lo malo."""
    e, j = etiqueta.astype(bool), juez.astype(bool)
    vp, fn = int((e & j).sum()), int((e & ~j).sum())
    fp, vn = int((~e & j).sum()), int((~e & ~j).sum())
    n = vp + fn + fp + vn
    acuerdo = (vp + vn) / n
    pe = ((vp + fn) * (vp + fp) + (fp + vn) * (fn + vn)) / n**2
    return {
        "n": n, "vp": vp, "fn": fn, "fp": fp, "vn": vn,
        "sensibilidad": vp / (vp + fn) if vp + fn else float("nan"),
        "especificidad": vn / (vn + fp) if vn + fp else float("nan"),
        "acuerdo": acuerdo,
        "kappa": (acuerdo - pe) / (1 - pe) if pe < 1 else float("nan"),
    }


def tasa_corregida(p_obs: float, sens: float, esp: float) -> float:
    """Rogan-Gladen: lleva la tasa de aprobación del juez a la tasa real, dado su error medido."""
    if sens + esp - 1 <= 0:
        return float("nan")
    return float(np.clip((p_obs + esp - 1) / (sens + esp - 1), 0, 1))


def corregir_con_intervalo(calibracion: pd.DataFrame, aprobados_objetivo: pd.Series,
                           n_boot: int = 2000, seed: int = 5) -> dict:
    """
    Tasa de aprobación corregida sobre mensajes sin etiqueta, con IC 95% por
    bootstrap que remuestrea tanto el set de calibración como el objetivo.
    `calibracion` necesita las columnas `etiqueta` y `juez` (booleanas).
    """
    rng = np.random.default_rng(seed)
    cal = calibracion[["etiqueta", "juez"]].to_numpy(dtype=bool)
    obj = aprobados_objetivo.to_numpy(dtype=bool)
    m = matriz(calibracion.etiqueta, calibracion.juez)
    puntual = tasa_corregida(obj.mean(), m["sensibilidad"], m["especificidad"])
    sims = []
    for _ in range(n_boot):
        c = cal[rng.integers(0, len(cal), len(cal))]
        o = obj[rng.integers(0, len(obj), len(obj))]
        buenos, malos = c[c[:, 0]], c[~c[:, 0]]
        if len(buenos) == 0 or len(malos) == 0:
            continue
        sims.append(tasa_corregida(o.mean(), buenos[:, 1].mean(), 1 - malos[:, 1].mean()))
    sims = np.array([s for s in sims if not np.isnan(s)])
    return {"observada": float(obj.mean()), "corregida": puntual,
            "ic_bajo": float(np.quantile(sims, 0.025)) if len(sims) else float("nan"),
            "ic_alto": float(np.quantile(sims, 0.975)) if len(sims) else float("nan")}


def recall_por_defecto(set_juez: pd.DataFrame, columna_juez: str) -> pd.DataFrame:
    """De los mensajes con cada defecto, qué parte rechazó el juez."""
    malos = set_juez[set_juez.defecto != "ninguno"]
    return (malos.assign(detectado=~malos[columna_juez].astype(bool))
            .groupby("defecto").agg(mensajes=("detectado", "size"), detectados=("detectado", "mean"))
            .reset_index())
