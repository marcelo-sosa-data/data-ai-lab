"""
Evaluación de la búsqueda, del umbral de abstención y de las respuestas.

- Búsqueda: posición del primer artículo correcto entre los k devueltos.
  Acierto@1, acierto@5 y MRR, por registro (formal / coloquial) y tipo.
- Error de versión: el artículo derogado aparece antes que el vigente.
- Umbral: se fija con las preguntas de desarrollo (cobertura de 95% de las
  que sí tienen respuesta) y se reporta con las de prueba.
- Respuestas: con un modelo (LLM o extractivo), si cita el artículo correcto,
  si el dato esperado aparece en el texto y si se abstuvo cuando debía.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .asistente import Asistente
from .recuperador import Configuracion, Recuperador
from .texto import normalizar

FECHA_EVALUACION = date(2026, 9, 1)     # semestre 2026-2, con la resolución ya vigente
COBERTURA = 0.95


def cargar_preguntas(ruta: Path) -> list[dict]:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def evaluar_busqueda(recuperador: Recuperador, preguntas: list[dict], config: Configuracion,
                     fecha: date = FECHA_EVALUACION, k: int = 5) -> pd.DataFrame:
    if config.vectorial:
        recuperador.precodificar([q["pregunta"] for q in preguntas])
    filas = []
    for q in preguntas:
        b = recuperador.buscar(q["pregunta"], fecha, k, config)
        ids = b.ids
        pos = next((i + 1 for i, x in enumerate(ids) if x in q["gold"]), None)
        pos_derogado = ids.index(q["derogado"]) + 1 if q.get("derogado") in ids else None
        filas.append({
            "config": config.nombre, "id": q["id"], "pregunta": q["pregunta"], "registro": q["registro"],
            "tipo": q["tipo"], "split": q["split"], "gold": "|".join(q["gold"]), "top1": ids[0],
            "posicion": pos, "confianza": b.confianza,
            "error_version": bool(pos_derogado and (pos is None or pos_derogado < pos)),
        })
    df = pd.DataFrame(filas)
    df["con_respuesta"] = df["tipo"] != "sin_respuesta"
    return df


def resumen_busqueda(df: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """Métricas sobre las preguntas que tienen respuesta en el corpus."""
    d = df[df["con_respuesta"]].copy()
    d["acierto@1"] = d["posicion"] == 1
    d["acierto@5"] = d["posicion"].notna()
    d["rr"] = 1 / d["posicion"].fillna(np.inf)
    por = por or ["config"]
    return (d.groupby(por, sort=False)
             .agg(n=("id", "size"), **{"acierto@1": ("acierto@1", "mean"), "acierto@5": ("acierto@5", "mean")},
                  mrr=("rr", "mean"))
             .reset_index())


def calibrar_umbral(df: pd.DataFrame, cobertura: float = COBERTURA) -> float:
    """Umbral que deja pasar `cobertura` de las preguntas con respuesta (en el set que se le dé)."""
    validas = df.loc[df["con_respuesta"], "confianza"]
    return float(np.quantile(validas, 1 - cobertura))


def evaluar_abstencion(df: pd.DataFrame, umbral: float) -> dict:
    responde = df["confianza"] >= umbral
    validas, ajenas = df["con_respuesta"], ~df["con_respuesta"]
    return {
        "umbral": round(umbral, 4),
        "validas": int(validas.sum()),
        "validas_respondidas": int((responde & validas).sum()),
        "sin_respuesta": int(ajenas.sum()),
        "sin_respuesta_abstenidas": int((~responde & ajenas).sum()),
        "ajenas_que_pasan": df.loc[responde & ajenas, "pregunta"].tolist(),
    }


def separacion(df: pd.DataFrame) -> float:
    """AUC de la confianza para distinguir preguntas con y sin respuesta (Mann-Whitney)."""
    pos = df.loc[df["con_respuesta"], "confianza"].to_numpy()
    neg = df.loc[~df["con_respuesta"], "confianza"].to_numpy()
    if not len(pos) or not len(neg):
        return float("nan")
    return float(((pos[:, None] > neg[None, :]) + 0.5 * (pos[:, None] == neg[None, :])).mean())


def evaluar_respuestas(asistente: Asistente, preguntas: list[dict],
                       fecha: date = FECHA_EVALUACION) -> pd.DataFrame:
    filas = []
    for q in preguntas:
        r = asistente.preguntar(q["pregunta"], fecha)
        citas = [f.id for f in r.citas]
        filas.append({
            "id": q["id"], "pregunta": q["pregunta"], "tipo": q["tipo"], "registro": q["registro"],
            "respondio": r.respondio, "abstencion": r.abstencion,
            "cita_correcta": any(c in q["gold"] for c in citas),
            "dato_en_texto": bool(q["dato"]) and normalizar(q["dato"]) in normalizar(r.texto),
            "citas_descartadas": len(r.citas_descartadas),
            "tokens": r.tokens_entrada + r.tokens_salida, "segundos": r.segundos,
        })
    df = pd.DataFrame(filas)
    df["con_respuesta"] = df["tipo"] != "sin_respuesta"
    return df


def resumen_respuestas(df: pd.DataFrame) -> dict:
    validas, ajenas = df[df["con_respuesta"]], df[~df["con_respuesta"]]
    return {
        "validas": len(validas),
        "respondidas": int(validas["respondio"].sum()),
        "cita_correcta": int(validas["cita_correcta"].sum()),
        "dato_en_texto": int(validas["dato_en_texto"].sum()),
        "sin_respuesta": len(ajenas),
        "abstenidas": int((~ajenas["respondio"]).sum()),
        "citas_descartadas": int(df["citas_descartadas"].sum()),
        "tokens": int(df["tokens"].sum()),
    }
