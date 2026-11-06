"""
Evaluación con corte temporal y modelo vigente.

- Evaluación: entrena con los semestres hasta t-2, calibra con t-1 y mide en t,
  el último semestre con desenlace conocido. Nada del semestre de prueba toca el modelo.
- Vigente: misma receta corrida un semestre más adelante (entrena hasta t-1, calibra con t)
  y puntúa el semestre en curso semana por semana.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import evaluacion as ev
from . import explicacion as ex
from . import modelos as mo
from .datos import Base, desenlaces
from .features import COLUMNAS, estaticas, matrices, semana

CAPACIDAD = 100                       # llamadas por semana entre los seis tutores
CAPACIDADES = (50, 100, 150, 200, 300)
POLITICAS = {
    "modelo": ("puntaje", None),
    "logistica": ("puntaje_log", None),
    "regla_ordenada": ("orden_regla", "regla"),
    "regla_actual": ("orden_reporte", "regla"),
}
MUESTRA_SHAP = 20_000


@dataclass
class Particion:
    entrenamiento: list[str]
    calibracion: str
    prueba: str


def particion(base: Base) -> Particion:
    cerrados = base.periodos_cerrados
    if len(cerrados) < 3:
        raise ValueError("Hacen falta al menos tres semestres cerrados")
    return Particion(cerrados[:-2], cerrados[-2], cerrados[-1])


def _ajustar(pnl: pd.DataFrame, entrenamiento: list[str], calibracion: str, rondas: int):
    tr = pnl[pnl.periodo.isin(entrenamiento)]
    ca = pnl[pnl.periodo == calibracion]
    m = mo.entrenar_lgbm(tr, rondas=rondas)
    lr = mo.entrenar_logistica(tr)
    cal_m = mo.Calibrador().ajustar(mo.predecir(m, ca), ca.deserta)
    cal_l = mo.Calibrador().ajustar(mo.predecir(lr, ca), ca.deserta)
    return m, lr, cal_m, cal_l, len(tr)


def _puntuar(df: pd.DataFrame, m, lr, cal_m, cal_l, seed: int = 0) -> pd.DataFrame:
    df = df.copy()
    # se ordena por el puntaje del modelo y se muestra la probabilidad calibrada: la isotónica
    # devuelve escalones y empataría a alumnos que el modelo sí distingue
    df["puntaje"] = mo.predecir(m, df)
    df["riesgo"] = cal_m(df.puntaje)
    df["puntaje_log"] = mo.predecir(lr, df)
    df["riesgo_log"] = cal_l(df.puntaje_log)
    df["regla"] = mo.regla_actual(df)
    df["orden_regla"] = mo.orden_regla(df)
    # la regla de hoy entrega la lista sin orden de prioridad: se simula como un orden al azar
    df["orden_reporte"] = np.random.default_rng(seed).random(len(df))
    return df


def evaluar(base: Base, pnl: pd.DataFrame, rondas: int = 600, capacidad: int = CAPACIDAD) -> dict:
    part = particion(base)
    m, lr, cal_m, cal_l, n_tr = _ajustar(pnl, part.entrenamiento, part.calibracion, rondas)
    te = _puntuar(pnl[pnl.periodo == part.prueba], m, lr, cal_m, cal_l)

    metricas = ev.metricas_semana(te, {"LightGBM": ("puntaje", "riesgo"), "Logística": ("puntaje_log", "riesgo_log")})
    regla = te.groupby("semana").apply(lambda g: pd.Series({
        "marcados": int(g.regla.sum()), "marcados_pct": g.regla.mean(),
        "precision": g[g.regla].deserta.mean(), "recall": g[g.regla].deserta.sum() / g.deserta.sum(),
        # el modelo con la misma cantidad de alumnos marcados
        "precision_modelo": g.nlargest(int(g.regla.sum()), "puntaje").deserta.mean(),
        "recall_modelo": g.nlargest(int(g.regla.sum()), "puntaje").deserta.sum() / g.deserta.sum(),
    }), include_groups=False).reset_index()

    cal = pd.concat([
        ev.calibracion(te.deserta, te.riesgo).assign(modelo="LightGBM calibrado"),
        ev.calibracion(te.deserta, te.puntaje).assign(modelo="LightGBM sin calibrar"),
        ev.calibracion(te.deserta, te.riesgo_log).assign(modelo="Logística calibrada"),
    ], ignore_index=True)
    eces = pd.DataFrame([{"modelo": "LightGBM calibrado", "ece": ev.ece(te.deserta, te.riesgo)},
                         {"modelo": "LightGBM sin calibrar", "ece": ev.ece(te.deserta, te.puntaje)},
                         {"modelo": "Logística calibrada", "ece": ev.ece(te.deserta, te.riesgo_log)}])

    fin = desenlaces(base)
    fin = fin[(fin.periodo == part.prueba) & ~fin.egresa][["id_alumno", "periodo", "deserta", "semana_abandono"]]
    capac, contactos_base = [], {}
    for pol, (orden, filtro) in POLITICAS.items():
        for k in CAPACIDADES:
            c = ev.simular_contactos(te, orden, k, filtro=filtro)
            capac.append({"politica": pol, "capacidad": k, **ev.resumen_contactos(c, fin)})
            if k == capacidad:
                contactos_base[pol] = c

    causas = None
    if base.causas is not None:
        filas = []
        cz = base.causas[base.causas.periodo == part.prueba]
        for pol in ("modelo", "regla_ordenada", "regla_actual"):
            d = cz.merge(contactos_base[pol], on=["id_alumno", "periodo"], how="left")
            d = d.merge(fin[["id_alumno", "periodo", "semana_abandono"]], on=["id_alumno", "periodo"])
            d["alcanzado"] = (d.semana_lista + 1) <= d.semana_abandono
            filas.append(d.groupby("causa").agg(desertores=("id_alumno", "size"), alcanzados=("alcanzado", "sum"))
                         .reset_index().assign(politica=pol))
        causas = pd.concat(filas, ignore_index=True)
        causas["alcanzados_pct"] = causas.alcanzados / causas.desertores

    muestra = te.sample(min(MUESTRA_SHAP, len(te)), random_state=1)
    sv, _ = ex.valores_shap(m, muestra)
    importancia = ex.importancia_global(sv)

    salida = {
        "metricas_semana": metricas, "regla_semana": regla, "calibracion": cal, "ece": eces,
        "capacidad": pd.DataFrame(capac), "importancia": importancia,
        "predicciones_prueba": te[["id_alumno", "periodo", "semana", "deserta", "semana_abandono", "puntaje",
                                   "riesgo", "riesgo_log", "regla"]],
        "particion": pd.DataFrame([{"entrenamiento": ", ".join(part.entrenamiento), "calibracion": part.calibracion,
                                    "prueba": part.prueba, "filas_entrenamiento": n_tr, "rondas": rondas,
                                    "capacidad": capacidad, "desertores_prueba": int(fin.deserta.sum()),
                                    "alumnos_prueba": len(fin),
                                    "desertores_semana_1": int(((fin.deserta == 1) & (fin.semana_abandono <= 2))
                                                               .sum())}]),
    }
    if causas is not None:
        salida["alcance_causas"] = causas
    return salida


def vigente(base: Base, pnl: pd.DataFrame, rondas: int = 600) -> dict:
    """Modelo con todos los semestres cerrados; puntúa el semestre en curso hasta la última semana con datos."""
    cerrados = base.periodos_cerrados
    m, lr, cal_m, cal_l, n_tr = _ajustar(pnl, cerrados[:-1], cerrados[-1], rondas)
    actual, w_act = base.periodo_actual, base.semana_actual
    act = _puntuar(pnl[pnl.periodo == actual], m, lr, cal_m, cal_l)
    riesgo = act[["id_alumno", "semana", "puntaje", "riesgo", "regla"]]

    ult = act[act.semana == w_act].reset_index(drop=True)
    sv, base_shap = ex.valores_shap(m, ult)
    textos = ex.razones(ult, sv)
    previo = act[act.semana == w_act - 1].set_index("id_alumno").riesgo
    al = base.alumnos.set_index("id_alumno")
    lista = pd.DataFrame({
        "id_alumno": ult.id_alumno, "codigo": al.codigo.reindex(ult.id_alumno).to_numpy(),
        "sede": ult.sede.astype(str), "carrera": ult.carrera.astype(str), "ciclo": ult.ciclo,
        "modalidad": np.where(ult.semipresencial == 1, "semipresencial", "presencial"),
        "puntaje": ult.puntaje, "riesgo": ult.riesgo, "riesgo_semana_anterior": previo.reindex(ult.id_alumno).to_numpy(),
        "asistencia_acum": ult.asistencia_acum, "asistencia_ult2": ult.asistencia_ult2,
        "nota_parcial": ult.nota_parcial, "cuotas_vencidas": ult.cuotas_vencidas, "regla": ult.regla,
        "razon_1": [t[0] if len(t) > 0 else "" for t in textos],
        "razon_2": [t[1] if len(t) > 1 else "" for t in textos],
        "razon_3": [t[2] if len(t) > 2 else "" for t in textos],
    }).sort_values("puntaje", ascending=False, ignore_index=True)
    lista["puesto"] = np.arange(1, len(lista) + 1)

    largo = pd.DataFrame(sv, columns=COLUMNAS)
    largo["id_alumno"] = ult.id_alumno
    largo = largo.melt(id_vars="id_alumno", var_name="variable", value_name="shap")
    valores = {(i, c): ex.describir(c, ult.at[j, c], w_act) for j, i in enumerate(ult.id_alumno) for c in COLUMNAS}
    largo["descripcion"] = [valores[(i, c)] for i, c in zip(largo.id_alumno, largo.variable)]

    # quienes no aparecieron en toda la semana: no hace falta modelo, se llama primero
    mx = matrices(base)
    sem = semana(mx, estaticas(base), w_act)
    sem = sem[(sem.periodo == actual).to_numpy()]
    ausentes = sem[sem.matriculado & ~sem.activo & (sem.semanas_sin_asistir <= 3)]
    ausentes = pd.DataFrame({
        "id_alumno": ausentes.id_alumno, "codigo": al.codigo.reindex(ausentes.id_alumno).to_numpy(),
        "sede": ausentes.sede.astype(str), "carrera": ausentes.carrera.astype(str), "ciclo": ausentes.ciclo,
        "semanas_sin_asistir": ausentes.semanas_sin_asistir, "asistencia_acum": ausentes.asistencia_acum,
        "cuotas_vencidas": ausentes.cuotas_vencidas,
    }).sort_values(["semanas_sin_asistir", "asistencia_acum"], ignore_index=True)

    return {"riesgo_actual": riesgo, "lista": lista, "shap_actual": largo, "ausentes": ausentes,
            "vigente": pd.DataFrame([{"periodo": actual, "semana": w_act, "entrenamiento": ", ".join(cerrados[:-1]),
                                      "calibracion": cerrados[-1], "filas_entrenamiento": n_tr,
                                      "valor_base_shap": base_shap, "activos": len(ult),
                                      "riesgo_medio_sin_calibrar": float(ult.puntaje.mean()),
                                      "riesgo_medio_calibrado": float(ult.riesgo.mean())}])}
