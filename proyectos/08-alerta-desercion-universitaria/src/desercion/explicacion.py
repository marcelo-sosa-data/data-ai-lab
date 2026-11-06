"""Explicaciones con SHAP: importancia global y las razones de cada alumno en texto."""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
import shap

from .features import COLUMNAS, DINAMICAS, EVALUACIONES

NOTAS = {"nota_pc1": ("PC1", EVALUACIONES["PC1"]), "nota_parcial": ("parcial", EVALUACIONES["Parcial"]),
         "nota_pc2": ("PC2", EVALUACIONES["PC2"])}


def valores_shap(modelo, X: pd.DataFrame) -> tuple[np.ndarray, float]:
    """Contribuciones en log-odds (antes de calibrar) y el valor base."""
    exp = shap.TreeExplainer(modelo)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)   # aviso de formato de salida de shap con LightGBM
        sv = exp.shap_values(X[COLUMNAS])
    if isinstance(sv, list):          # algunas versiones devuelven una matriz por clase
        sv = sv[1]
    base = exp.expected_value
    base = float(base[1] if np.ndim(base) else base)
    return np.asarray(sv), base


def importancia_global(sv: np.ndarray) -> pd.DataFrame:
    imp = pd.DataFrame({"variable": COLUMNAS, "shap_medio": np.abs(sv).mean(axis=0)})
    imp["tipo"] = np.where(imp.variable.isin(DINAMICAS), "de la semana", "de la ficha")
    return imp.sort_values("shap_medio", ascending=False, ignore_index=True)


def _pct(v):
    return f"{v:.0%}"


def describir(variable: str, valor, semana: int) -> str:
    """Texto corto para tutoría: qué dato empuja el riesgo."""
    falta = valor is None or (isinstance(valor, float) and math.isnan(valor))
    if variable in NOTAS:
        nombre, sem = NOTAS[variable]
        if falta:
            return f"no rindió la {nombre}" if semana >= sem else f"aún sin nota de {nombre}"
        return f"{valor:.1f} en la {nombre}"
    if falta:
        sin_dato = {"promedio_anterior": "sin promedio previo (primer ciclo)",
                    "asistencia_semestre_anterior": "sin ciclo anterior registrado",
                    "caida_asistencia": "aún sin historia para comparar asistencia",
                    "entrega_ult2": "sin tareas en las dos últimas semanas",
                    "entrega_tareas": "sin tareas todavía"}
        return sin_dato.get(variable, f"sin dato de {variable.replace('_', ' ')}")
    textos = {
        "asistencia_acum": lambda v: f"asistencia acumulada de {_pct(v)}",
        "asistencia_ult2": lambda v: f"asistió al {_pct(v)} en las dos últimas semanas",
        "asistencia_reciente": lambda v: f"asistencia reciente de {_pct(v)}",
        "caida_asistencia": lambda v: f"asistencia {abs(v) * 100:.0f} puntos {'abajo' if v < 0 else 'arriba'} "
                                      "de sus primeras semanas",
        "semanas_sin_asistir": lambda v: f"{v:.0f} semana(s) seguidas sin asistir",
        "ingresos_ult2": lambda v: f"{v:.1f} ingresos por semana al aula virtual",
        "ratio_ingresos": lambda v: f"aula virtual al {_pct(v)} de su ritmo habitual",
        "minutos_ult2": lambda v: f"{v:.0f} min por semana en el aula virtual",
        "entrega_tareas": lambda v: f"entregó el {_pct(v)} de las tareas",
        "entrega_ult2": lambda v: f"entregó el {_pct(v)} de las tareas recientes",
        "evaluaciones_no_rendidas": lambda v: f"{v:.0f} evaluación(es) sin rendir",
        "promedio_evaluaciones": lambda v: f"promedio de {v:.1f} en lo que va del ciclo",
        "cuotas_vencidas": lambda v: f"{v:.0f} cuota(s) vencida(s)",
        "semanas_atraso": lambda v: f"{v:.0f} semanas de atraso en pagos",
        "cuotas_pagadas_tarde": lambda v: f"pagó {v:.0f} cuota(s) tarde",
        "ciclo": lambda v: "primer ciclo" if v == 1 else f"ciclo {v:.0f}",
        "promedio_anterior": lambda v: f"promedio del ciclo anterior de {v:.1f}",
        "desaprobados_acumulados": lambda v: f"{v:.0f} cursos desaprobados en su historial",
        "asistencia_semestre_anterior": lambda v: f"asistencia del ciclo anterior de {_pct(v)}",
        "retiros_previos": lambda v: f"{v:.0f} retiro(s) en ciclos anteriores",
        "semipresencial": lambda v: "modalidad semipresencial" if v else "modalidad presencial",
        "trabaja": lambda v: "trabaja" if v else "no trabaja",
        "edad": lambda v: f"{v:.0f} años",
        "beca_pct": lambda v: "sin beca" if v == 0 else f"beca de {v:.0f}%",
        "escala_pension": lambda v: f"escala de pensión {'ABCDE'[int(v)]}",
        "primera_generacion": lambda v: "primera generación en la universidad" if v else "padres con estudios",
        "tiempo_traslado_min": lambda v: f"{v:.0f} min de traslado",
        "puntaje_ingreso": lambda v: f"puntaje de ingreso {v:.0f}",
        "colegio_publico": lambda v: "colegio público" if v else "colegio privado",
        "creditos": lambda v: f"{v:.0f} créditos",
        "cursos": lambda v: f"{v:.0f} cursos",
        "semana": lambda v: f"semana {v:.0f} del ciclo",
        "sede": lambda v: f"sede {v}",
        "carrera": lambda v: str(v),
    }
    f = textos.get(variable)
    return f(valor) if f else f"{variable}: {valor}"


def razones(X: pd.DataFrame, sv: np.ndarray, top: int = 3) -> list[list[str]]:
    """Las `top` variables que más suben el riesgo de cada fila, en texto."""
    salida = []
    cols = np.array(COLUMNAS)
    for i in range(len(X)):
        fila = X.iloc[i]
        orden = np.argsort(-sv[i])
        textos = [describir(c, fila[c], int(fila["semana"])) for c in cols[orden[:top]] if sv[i][COLUMNAS.index(c)] > 0]
        salida.append(textos)
    return salida
