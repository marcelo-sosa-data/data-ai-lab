"""
Set de calibración del juez: mensajes con su etiqueta de revisión.

Parte de los mensajes que el agente registró en una corrida y a la mitad le
inserta un defecto conocido (promesa falsa, incoherencia, falta de sustento,
culpa al cliente, derivación sin plazo, dato personal). La etiqueta sale de
esa construcción: sé qué tiene cada mensaje porque lo puse yo. Con datos
reales serían las marcas de dos revisores de calidad sobre una muestra.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

SALUDOS = ["Hola, sobre", "Buenas tardes, sobre", "Estimado cliente, sobre", "Hola, gracias por escribirnos. Sobre"]
CIERRES = ["", "", " Gracias por su paciencia.", " Quedamos atentos."]

PROMESAS = [" Ya le devolvimos el monto a su tarjeta.", " Le abonamos el importe completo en las próximas horas.",
            " Igual hemos abonado el monto como gesto comercial."]
CULPAS = [" Le recomendamos revisar mejor sus consumos antes de presentar un reclamo.",
          " Esto suele pasar cuando el cliente no lee las condiciones de su tarjeta.",
          " Le pedimos más cuidado la próxima vez para no hacernos perder tiempo."]
GENERICOS = ["Hola, sobre su reclamo {cod}: revisamos su caso y no procede. Gracias por escribirnos.",
             "Hola, sobre su reclamo {cod}: luego de la evaluación, no corresponde atender su pedido.",
             "Hola, sobre su reclamo {cod}: ya realizamos la revisión correspondiente y su caso quedó atendido."]
SIN_PLAZO = ["Hola, sobre su reclamo {cod}: lo estamos revisando y le avisaremos.",
             "Hola, sobre su reclamo {cod}: pasamos su caso a otra área para que lo vean."]


# los defectos que aplican a menos acciones pesan más, para que todos tengan una cantidad parecida
PESO_DEFECTO = {"culpa_cliente": 1.0, "dato_personal": 1.0, "promesa_falsa": 1.5, "incoherente": 3.0,
                "sin_sustento": 3.0, "sin_plazo": 1.5}


def _variar(mensaje: str, rng) -> str:
    """Cambia saludo y cierre para que el formato no delate cuáles son los buenos."""
    m = re.sub(r"^Hola, sobre", str(rng.choice(SALUDOS)), mensaje)
    return m + str(rng.choice(CIERRES))


def _defectos_posibles(accion: str) -> list[str]:
    posibles = ["culpa_cliente", "dato_personal"]
    if accion != "ABONAR":
        posibles.append("promesa_falsa")
    if accion in ("ABONAR", "NO_PROCEDE"):
        posibles += ["incoherente", "sin_sustento"]
    if accion.startswith("ESCALAR"):
        posibles.append("sin_plazo")
    return posibles


def _aplicar(defecto: str, mensaje: str, codigo: str, accion: str, rng) -> str:
    if defecto == "promesa_falsa":
        return mensaje + str(rng.choice(PROMESAS))
    if defecto == "culpa_cliente":
        return mensaje + str(rng.choice(CULPAS))
    if defecto == "dato_personal":
        tarjeta = "4557 88" + "".join(str(d) for d in rng.integers(0, 10, 2)) + " " + \
                  " ".join("".join(str(d) for d in rng.integers(0, 10, 4)) for _ in range(2))
        return mensaje + f" La devolución o el seguimiento quedan asociados a su tarjeta {tarjeta}."
    if defecto == "incoherente":
        if accion == "ABONAR":
            return re.sub(r"y corresponde la devolución\..*$",
                          "y no corresponde una devolución, por lo que su reclamo queda cerrado.", mensaje)
        nuevo = re.sub(r"(por eso )?no (procede|corresponde)( una)?( la)? devolución( adicional)?",
                       "sí procede la devolución", mensaje, count=1, flags=re.I)
        return nuevo if nuevo != mensaje else mensaje + " Su reclamo procede y le haremos la devolución."
    if defecto == "sin_sustento":
        return str(rng.choice(GENERICOS)).format(cod=codigo)
    if defecto == "sin_plazo":
        return str(rng.choice(SIN_PLAZO)).format(cod=codigo)
    raise ValueError(defecto)


def armar(resultados: pd.DataFrame, n: int = 160, prop_defecto: float = 0.5, seed: int = 21) -> pd.DataFrame:
    """
    `resultados` necesita id_reclamo, codigo, accion, monto_abonado y mensaje
    (lo que sale de evaluacion.tabla_resultados). Devuelve una fila por mensaje
    con su defecto y la etiqueta (True = aprueba la revisión).
    """
    rng = np.random.default_rng(seed)
    base = resultados[resultados.mensaje.str.len() > 0]
    # misma cantidad por acción, para que las derivaciones no tapen a los abonos
    por_accion = max(1, n // base.accion.nunique())
    base = pd.concat([g.sample(min(len(g), por_accion), random_state=seed) for _, g in base.groupby("accion")])
    filas = []
    for r in base.itertuples():
        defecto = "ninguno"
        mensaje = r.mensaje
        if rng.random() < prop_defecto:
            posibles = _defectos_posibles(r.accion)
            pesos = np.array([PESO_DEFECTO[d] for d in posibles])
            defecto = str(rng.choice(posibles, p=pesos / pesos.sum()))
            nuevo = _aplicar(defecto, mensaje, r.codigo, r.accion, rng)
            if nuevo == mensaje:  # la plantilla no tenía la frase a cambiar
                defecto = "ninguno"
            mensaje = nuevo
        filas.append({"id_reclamo": r.id_reclamo, "accion": r.accion, "monto_abonado": r.monto_abonado,
                      "defecto": defecto, "etiqueta": defecto == "ninguno", "mensaje": _variar(mensaje, rng)})
    return pd.DataFrame(filas).reset_index(drop=True)
