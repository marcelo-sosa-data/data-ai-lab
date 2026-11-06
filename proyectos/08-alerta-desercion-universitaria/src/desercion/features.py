"""
Variables por alumno y semana del semestre.

Todo lo que se calcula para la semana w usa solo lo registrado hasta el cierre de
esa semana: asistencia y aula virtual de las semanas 1..w, notas de evaluaciones
tomadas hasta w y cuotas pagadas hasta w. Así una fila de la semana 6 de 2024-1
se ve igual que se habría visto ese domingo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .datos import SEMANAS, Base, desenlaces, siguiente_periodo

EVALUACIONES = {"PC1": 4, "Parcial": 8, "PC2": 12}   # la final (semana 16) llega tarde para alertar

ESTATICAS = ["ciclo", "cursos", "creditos", "beca_pct", "promedio_anterior", "desaprobados_acumulados",
             "retiros_previos", "asistencia_semestre_anterior", "semipresencial", "trabaja", "edad", "colegio_publico", "escala_pension",
             "primera_generacion", "tiempo_traslado_min", "puntaje_ingreso"]
DINAMICAS = ["semana", "asistencia_acum", "asistencia_ult2", "asistencia_reciente", "caida_asistencia",
             "semanas_sin_asistir", "ingresos_ult2", "ratio_ingresos", "minutos_ult2", "entrega_tareas", "entrega_ult2",
             "nota_pc1", "nota_parcial", "nota_pc2", "evaluaciones_no_rendidas", "promedio_evaluaciones",
             "cuotas_vencidas", "semanas_atraso", "cuotas_pagadas_tarde"]
CATEGORICAS = ["sede", "carrera"]
COLUMNAS = ESTATICAS + DINAMICAS + CATEGORICAS


@dataclass
class Matrices:
    """Series semanales por matrícula, en arrays de (n_matriculas, 17); la columna 0 no se usa."""
    claves: pd.DataFrame
    sesiones: np.ndarray
    asistidas: np.ndarray
    matriculado: np.ndarray
    ingresos: np.ndarray
    minutos: np.ndarray
    tareas: np.ndarray
    entregadas: np.ndarray
    notas: dict[str, np.ndarray]
    venc: np.ndarray
    pago: np.ndarray


def _posiciones(idx: pd.MultiIndex, df: pd.DataFrame) -> np.ndarray:
    return idx.get_indexer(pd.MultiIndex.from_frame(df[["id_alumno", "periodo"]]))


def _a_matriz(df: pd.DataFrame, idx: pd.MultiIndex, col: str, n: int) -> np.ndarray:
    out = np.zeros((n, SEMANAS + 1))
    i = _posiciones(idx, df)
    out[i, df.semana.to_numpy()] = df[col].to_numpy()
    return out


def matrices(base: Base) -> Matrices:
    claves = base.matriculas[["id_alumno", "periodo"]].reset_index(drop=True)
    n = len(claves)
    pos = pd.MultiIndex.from_frame(claves)
    a, lv = base.asistencia, base.aula_virtual
    matric = _a_matriz(a.assign(uno=1), pos, "uno", n).astype(bool)
    ev = base.evaluaciones.set_index(["id_alumno", "periodo", "evaluacion"]).nota
    notas = {}
    for nombre in EVALUACIONES:
        s = ev.xs(nombre, level="evaluacion") if nombre in ev.index.get_level_values(2) else pd.Series(dtype=float)
        notas[nombre] = s.reindex(pos).to_numpy(dtype=float)
    cu = base.cuotas.copy()
    cu["semana_pago"] = cu.semana_pago.astype(float)
    ncu = int(cu.cuota.max())
    venc = np.full((n, ncu), np.nan)
    pago = np.full((n, ncu), np.nan)
    i = _posiciones(pos, cu)
    venc[i, cu.cuota.to_numpy() - 1] = cu.semana_vencimiento.to_numpy()
    pago[i, cu.cuota.to_numpy() - 1] = cu.semana_pago.to_numpy()
    return Matrices(claves, _a_matriz(a, pos, "sesiones", n), _a_matriz(a, pos, "asistidas", n), matric,
                    _a_matriz(lv, pos, "ingresos", n), _a_matriz(lv, pos, "minutos", n),
                    _a_matriz(lv, pos, "tareas", n), _a_matriz(lv, pos, "tareas_entregadas", n), notas, venc, pago)


def _ratio(num, den):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def estaticas(base: Base) -> pd.DataFrame:
    al = base.alumnos
    m = base.matriculas.merge(al, on="id_alumno", how="left")
    # asistencia del semestre anterior: el compromiso de un alumno se arrastra de un ciclo a otro
    prev = base.asistencia.groupby(["id_alumno", "periodo"])[["asistidas", "sesiones"]].sum().reset_index()
    prev["periodo"] = prev.periodo.map(siguiente_periodo)
    prev["asistencia_semestre_anterior"] = prev.asistidas / prev.sesiones
    m = m.merge(prev[["id_alumno", "periodo", "asistencia_semestre_anterior"]], on=["id_alumno", "periodo"],
                how="left")
    anio = m.periodo.str[:4].astype(int) + (m.periodo.str[-1] == "2") * 0.5
    anio_ing = m.periodo_ingreso.str[:4].astype(int) + (m.periodo_ingreso.str[-1] == "2") * 0.5
    return pd.DataFrame({
        "id_alumno": m.id_alumno, "periodo": m.periodo,
        "ciclo": m.ciclo, "cursos": m.cursos, "creditos": m.creditos, "beca_pct": m.beca_pct,
        "promedio_anterior": m.promedio_anterior, "desaprobados_acumulados": m.desaprobados_acumulados,
        "retiros_previos": m.retiros_previos, "asistencia_semestre_anterior": m.asistencia_semestre_anterior,
        "semipresencial": (m.modalidad == "semipresencial").astype(int), "trabaja": m.trabaja.astype(int),
        "edad": (m.edad_ingreso + (anio - anio_ing)).round(0), "colegio_publico": (m.colegio == "público").astype(int),
        "escala_pension": m.escala_pension.map({e: i for i, e in enumerate("ABCDE")}),
        "primera_generacion": m.primera_generacion.astype(int), "tiempo_traslado_min": m.tiempo_traslado_min,
        "puntaje_ingreso": m.puntaje_ingreso,
        "sede": pd.Categorical(m.sede), "carrera": pd.Categorical(m.carrera),
    })


def semana(mx: Matrices, est: pd.DataFrame, w: int) -> pd.DataFrame:
    """Variables al cierre de la semana w para todas las matrículas, con la marca de si sigue activo."""
    s, a = mx.sesiones[:, 1:w + 1], mx.asistidas[:, 1:w + 1]
    ult = slice(max(w - 1, 1), w + 1)
    prev = slice(1, max(w - 1, 1))
    asis_prev = _ratio(mx.asistidas[:, prev].sum(1), mx.sesiones[:, prev].sum(1))
    asis_ult = _ratio(mx.asistidas[:, ult].sum(1), mx.sesiones[:, ult].sum(1))

    # semanas seguidas sin asistir al cierre de w (solo cuentan las semanas en que estaba matriculado)
    sin = (a == 0) & mx.matriculado[:, 1:w + 1]
    racha = np.zeros(len(a), int)
    vivo = np.ones(len(a), bool)
    for k in range(w - 1, -1, -1):
        vivo &= sin[:, k]
        racha += vivo

    # promedio exponencial de la asistencia semanal: pesa más lo último sin tirar la historia
    reciente = np.full(len(a), np.nan)
    for k in range(1, w + 1):
        tasa = _ratio(mx.asistidas[:, k], mx.sesiones[:, k])
        ok = ~np.isnan(tasa)
        reciente = np.where(ok & np.isnan(reciente), tasa, reciente)
        reciente = np.where(ok, 0.6 * reciente + 0.4 * np.nan_to_num(tasa), reciente)

    ing_prev = mx.ingresos[:, prev].mean(1) if w > 2 else np.full(len(a), np.nan)
    ing_ult = mx.ingresos[:, ult].mean(1)
    df = est.copy()
    df["semana"] = w
    df["asistencia_acum"] = _ratio(a.sum(1), s.sum(1))
    df["asistencia_ult2"] = asis_ult
    df["asistencia_reciente"] = reciente
    df["caida_asistencia"] = asis_ult - asis_prev if w > 2 else np.nan
    df["semanas_sin_asistir"] = racha
    df["ingresos_ult2"] = ing_ult
    df["ratio_ingresos"] = (ing_ult + 0.5) / (ing_prev + 0.5)
    df["minutos_ult2"] = mx.minutos[:, ult].mean(1)
    df["entrega_tareas"] = _ratio(mx.entregadas[:, 1:w + 1].sum(1), mx.tareas[:, 1:w + 1].sum(1))
    df["entrega_ult2"] = _ratio(mx.entregadas[:, ult].sum(1), mx.tareas[:, ult].sum(1))

    tomadas = [nm for nm, sem in EVALUACIONES.items() if sem <= w]
    for nm, col in (("PC1", "nota_pc1"), ("Parcial", "nota_parcial"), ("PC2", "nota_pc2")):
        df[col] = mx.notas[nm] if nm in tomadas else np.nan
    if tomadas:
        mat = np.column_stack([mx.notas[nm] for nm in tomadas])
        df["evaluaciones_no_rendidas"] = np.isnan(mat).sum(1)
        df["promedio_evaluaciones"] = np.nanmean(np.where(np.isnan(mat), 0, mat), axis=1)
    else:
        df["evaluaciones_no_rendidas"] = 0
        df["promedio_evaluaciones"] = np.nan

    vencida = (mx.venc <= w) & (np.isnan(mx.pago) | (mx.pago > w))
    df["cuotas_vencidas"] = vencida.sum(1)
    df["semanas_atraso"] = np.where(vencida, w - mx.venc, 0).max(1)
    df["cuotas_pagadas_tarde"] = ((mx.venc <= w) & (mx.pago <= w) & (mx.pago > mx.venc)).sum(1)

    # activo: sigue matriculado y asistió o entregó algo esta semana. Quien no apareció en toda
    # la semana ya no necesita un modelo: va a la lista de ausentes.
    df["matriculado"] = mx.matriculado[:, w]
    df["activo"] = mx.matriculado[:, w] & ((mx.asistidas[:, w] > 0) | (mx.entregadas[:, w] > 0))
    return df


def panel(base: Base, semanas=range(2, SEMANAS + 1), solo_activos: bool = True,
          mx: Matrices | None = None) -> pd.DataFrame:
    """Una fila por alumno activo y semana, con el desenlace del semestre."""
    mx = mx or matrices(base)
    est = estaticas(base)
    limite = base.matriculas.periodo.map(base.periodos.set_index("periodo").semanas_con_datos).to_numpy()
    fin = desenlaces(base)[["id_alumno", "periodo", "deserta", "semana_abandono"]]
    partes = []
    for w in semanas:
        df = semana(mx, est, w)
        df = df[(limite >= w) & (df.activo if solo_activos else True)]
        partes.append(df)
    out = pd.concat(partes, ignore_index=True)
    out = out.merge(fin, on=["id_alumno", "periodo"], how="left")
    for c in CATEGORICAS:
        out[c] = pd.Categorical(out[c].astype(str), categories=sorted(est[c].astype(str).unique()))
    return out
