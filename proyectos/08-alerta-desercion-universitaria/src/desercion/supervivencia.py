"""
Análisis de supervivencia sobre la permanencia dentro del semestre.

El tiempo es la semana en que el alumno deja de ir (1 a 16) o 17 si termina el
ciclo y no se vuelve a matricular. Quien vuelve queda censurado en 17. Los
egresados no entran: no están en riesgo de desertar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.statistics import multivariate_logrank_test

from .datos import SEMANA_ENTRE_SEMESTRES

GRUPOS = {
    "ciclo": lambda d: pd.cut(d.ciclo, [0, 2, 4, 10], labels=["1-2", "3-4", "5 a 10"]).astype(str),
    "modalidad": lambda d: np.where(d.semipresencial == 1, "semipresencial", "presencial"),
    "trabaja": lambda d: np.where(d.trabaja == 1, "trabaja", "no trabaja"),
    "beca": lambda d: np.where(d.beca_pct > 0, "con beca", "sin beca"),
}

COVARIABLES_COX = {
    "primer_año": "Ciclo 1 o 2",
    "trabaja": "Trabaja",
    "semipresencial": "Semipresencial",
    "con_beca": "Con beca",
    "traslado_90": "Más de 90 min de traslado",
    "primera_generacion": "Primera generación",
    "asistencia_bajo_80": "Asistencia < 80% a la semana 4",
    "pc1_desaprobada": "PC1 desaprobada o no rendida",
    "cuota_vencida": "Cuota vencida a la semana 4",
}


def tabla(estaticas: pd.DataFrame, desenlace: pd.DataFrame) -> pd.DataFrame:
    d = desenlace[desenlace.deserta.notna() & ~desenlace.egresa]
    d = d.merge(estaticas.drop(columns=["ciclo"]), on=["id_alumno", "periodo"], how="left")
    d["evento"] = d.deserta.astype(int)
    d["duracion"] = np.where(d.evento == 1, d.semana_abandono, SEMANA_ENTRE_SEMESTRES).astype(int)
    return d


def kaplan_meier(t: pd.DataFrame, grupo: str) -> tuple[pd.DataFrame, float]:
    """Curvas de permanencia por grupo y p-valor del log-rank."""
    etiquetas = pd.Series(GRUPOS[grupo](t), index=t.index)
    curvas = []
    for valor in sorted(etiquetas.unique()):
        s = t[etiquetas == valor]
        km = KaplanMeierFitter().fit(s.duracion, s.evento)
        sf = km.survival_function_.iloc[:, 0]
        ic = km.confidence_interval_survival_function_
        curvas.append(pd.DataFrame({"grupo": grupo, "valor": valor, "semana": sf.index.astype(int),
                                    "permanencia": sf.to_numpy(), "ic_inf": ic.iloc[:, 0].to_numpy(),
                                    "ic_sup": ic.iloc[:, 1].to_numpy(), "alumnos": len(s)}))
    p = multivariate_logrank_test(t.duracion, etiquetas, t.evento).p_value
    return pd.concat(curvas, ignore_index=True), float(p)


def riesgo_semanal(t: pd.DataFrame) -> pd.DataFrame:
    """Riesgo discreto: de los que seguían yendo al empezar la semana, qué parte dejó de ir esa semana."""
    filas = []
    for w in range(1, SEMANA_ENTRE_SEMESTRES + 1):
        en_riesgo = int((t.duracion >= w).sum())
        eventos = int(((t.duracion == w) & (t.evento == 1)).sum())
        filas.append({"semana": w, "en_riesgo": en_riesgo, "abandonos": eventos,
                      "riesgo": eventos / en_riesgo if en_riesgo else np.nan})
    return pd.DataFrame(filas)


def cox_landmark(panel_semana: pd.DataFrame, semana: int = 4) -> pd.DataFrame:
    """
    Cox con lo que se sabe en la semana `semana` (análisis landmark): solo alumnos que seguían yendo
    esa semana y el tiempo se cuenta desde ahí. Devuelve hazard ratios con IC 95%.
    """
    d = panel_semana[(panel_semana.semana == semana) & panel_semana.deserta.notna()].copy()
    x = pd.DataFrame({
        "primer_año": (d.ciclo <= 2).astype(int),
        "trabaja": d.trabaja,
        "semipresencial": d.semipresencial,
        "con_beca": (d.beca_pct > 0).astype(int),
        "traslado_90": ((d.tiempo_traslado_min > 90) & (d.semipresencial == 0)).astype(int),
        "primera_generacion": d.primera_generacion,
        "asistencia_bajo_80": (d.asistencia_acum < 0.8).astype(int),
        "pc1_desaprobada": (d.nota_pc1.isna() | (d.nota_pc1 < 10.5)).astype(int),
        "cuota_vencida": (d.cuotas_vencidas >= 1).astype(int),
    })
    x["evento"] = d.deserta.astype(int).to_numpy()
    x["duracion"] = np.where(x.evento == 1, d.semana_abandono, SEMANA_ENTRE_SEMESTRES) - semana
    cph = CoxPHFitter().fit(x, duration_col="duracion", event_col="evento")
    s = cph.summary
    out = pd.DataFrame({"variable": s.index, "descripcion": [COVARIABLES_COX[v] for v in s.index],
                        "hr": s["exp(coef)"].to_numpy(), "ic_inf": s["exp(coef) lower 95%"].to_numpy(),
                        "ic_sup": s["exp(coef) upper 95%"].to_numpy(), "p": s["p"].to_numpy(),
                        "prevalencia": x[s.index].mean().to_numpy()})
    out.attrs["concordancia"] = float(cph.concordance_index_)
    out.attrs["alumnos"] = len(x)
    return out.sort_values("hr", ascending=False, ignore_index=True)
