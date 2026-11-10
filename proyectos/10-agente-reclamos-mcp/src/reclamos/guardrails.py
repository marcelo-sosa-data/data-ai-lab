"""
Controles sobre lo que entra al modelo y lo que sale hacia el cliente.

Entrada: el texto del reclamo se enmascara (DNI, tarjeta, celular, correo)
antes de llegar al LLM y se revisa si trae instrucciones para el asistente.
Salida: el mensaje final no puede llevar datos personales ni afirmar un abono
que no está registrado en los sistemas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .regla_actual import normalizar

_TARJETA = re.compile(r"\b(?:\d[ -]?){12}(\d{4})\b")
_DNI = re.compile(r"(?<!\d)\d{8}(?!\d)")
_CELULAR = re.compile(r"(?<!\d)9\d{8}(?!\d)")
_CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

PATRONES_INYECCION = [
    r"ignora (tus|las) (instrucciones|reglas)",
    r"olvida (tus|las) (instrucciones|reglas)",
    r"\bsistema\s*:",
    r"\bsystem\s*:",
    r"como asistente debes",
    r"sin (revisar|verificar|verificacion)",
    r"datos del (ultimo|otro|siguiente) cliente",
    r"eres un nuevo asistente",
]

_ABONO_AFIRMADO = re.compile(
    r"(hemos abonado|abonamos|le abonamos|se abono|se le abono|hemos devuelto|devolvimos|"
    r"reembolsamos|hemos reembolsado|ya tiene (el|su) abono|abono de s/)")
_MONTO = re.compile(r"s/\s?(\d+(?:[.,]\d{1,2})?)")


def enmascarar(texto: str) -> str:
    """Reemplaza datos personales por marcas. La tarjeta conserva los últimos 4."""
    texto = _CORREO.sub("[CORREO]", texto)
    texto = _TARJETA.sub(lambda m: f"[TARJETA ****{m.group(1)}]", texto)
    texto = _CELULAR.sub("[CELULAR]", texto)
    return _DNI.sub("[DNI]", texto)


def datos_personales(texto: str) -> list[str]:
    """Qué tipos de dato personal aparecen sin enmascarar."""
    hallados = []
    if _TARJETA.search(texto):
        hallados.append("tarjeta")
    if _CELULAR.search(texto):
        hallados.append("celular")
    elif _DNI.search(texto):
        hallados.append("dni")
    if _CORREO.search(texto):
        hallados.append("correo")
    return hallados


def detectar_inyeccion(texto: str) -> list[str]:
    """Patrones de instrucciones dirigidas al asistente dentro del reclamo."""
    t = normalizar(texto)
    return [p for p in PATRONES_INYECCION if re.search(p, t)]


@dataclass
class RevisionSalida:
    ok: bool
    problemas: list[str] = field(default_factory=list)


def revisar_mensaje(mensaje: str, abonos: list[float], resultado: str) -> RevisionSalida:
    """
    Revisa el mensaje al cliente antes de registrarlo.

    `abonos` son los montos que de verdad se abonaron en este reclamo y
    `resultado` lo que el agente declara (procede_abonado, no_procede, derivado).
    """
    problemas = []
    if not 40 <= len(mensaje) <= 1500:
        problemas.append("El mensaje debe tener entre 40 y 1500 caracteres.")
    pii = datos_personales(mensaje)
    if pii:
        problemas.append(f"El mensaje expone datos personales: {', '.join(pii)}.")
    t = normalizar(mensaje)
    if _ABONO_AFIRMADO.search(t) and not abonos:
        problemas.append("El mensaje afirma un abono que no está registrado.")
    if abonos:
        montos = {round(float(m.replace(",", ".")), 2) for m in _MONTO.findall(t)}
        if montos and not any(abs(m - a) < 0.01 for m in montos for a in abonos):
            problemas.append(f"El monto del mensaje no coincide con el abono registrado (S/ {abonos[0]:.2f}).")
    if resultado == "procede_abonado" and not abonos:
        problemas.append("El resultado es procede_abonado pero no hay abono registrado.")
    return RevisionSalida(not problemas, problemas)
