"""
Tiempos del proceso: cuánto trabaja cada área, cuánto espera el trámite y
cuánto dura cada caso contra el plazo del reglamento.

La espera se mide desde que terminó la actividad anterior del mismo trámite
hasta que el área empezó la suya. Las actividades sin hora de inicio
(Tesorería, firma, respuestas del estudiante) solo tienen tiempo total.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import catalogos as K
from .calendario import HORAS_DIA, a_habiles


def tiempos_evento(eventos: pd.DataFrame) -> pd.DataFrame:
    """Agrega a cada evento la espera, el servicio y el tiempo total en horas hábiles."""
    ev = eventos.sort_values(["id_tramite", "orden"]).copy()
    ev["fin_anterior"] = ev.groupby("id_tramite")["fin"].shift()
    h_fin = a_habiles(ev["fin"])
    h_prev = np.where(ev["fin_anterior"].notna(), a_habiles(ev["fin_anterior"].fillna(ev["fin"])), np.nan)
    tiene_ini = ev["inicio"].notna().to_numpy()
    h_ini = np.where(tiene_ini, a_habiles(ev["inicio"].fillna(ev["fin"])), np.nan)
    ev["total_h"] = h_fin - h_prev
    ev["servicio_h"] = np.where(tiene_ini, h_fin - h_ini, np.nan)
    ev["espera_h"] = np.where(tiene_ini, h_ini - h_prev, np.nan)
    ev["total_dias_cal"] = (ev["fin"] - ev["fin_anterior"]).dt.total_seconds() / 86400
    return ev


def casos(log, ev_t: pd.DataFrame | None = None) -> pd.DataFrame:
    """Una fila por trámite: duración, plazo, reprocesos y excepciones."""
    ev = log.eventos
    tr = log.tramites.copy()
    tr["duracion_dias"] = (tr["fin"] - tr["registro"]).dt.total_seconds() / 86400
    tr["dias_habiles"] = np.where(tr["fin"].notna(),
                                  (a_habiles(tr["fin"].fillna(tr["registro"])) -
                                   a_habiles(tr["registro"])) / HORAS_DIA, np.nan)
    tr["plazo"] = tr["tipo"].map(K.PLAZO_DIAS)
    tr["fuera_plazo"] = tr["dias_habiles"] > tr["plazo"]
    cuenta = ev.pivot_table(index="id_tramite", columns="actividad", values="fin", aggfunc="count",
                            fill_value=0)

    def col(a):
        return tr["id_tramite"].map(cuenta[a] if a in cuenta else {}).fillna(0).astype(int)

    obs = sum(col(a) for a in K.OBSERVACIONES)
    tr["observaciones"] = obs
    tr["reproceso"] = obs > 0
    tr["excepcion"] = col(K.DEVOLVER_PLAZO) > 0
    tr["vueltas_secretaria"] = col(K.REVISAR_EXP) + col(K.REVISAR_SOL)
    tr["eventos"] = tr["id_tramite"].map(ev.groupby("id_tramite").size()).fillna(0).astype(int)
    lim = tr["registro"].map(lambda f: K.semestre_de(f).limite_retiro if pd.notna(f) else pd.NaT)
    tr["dias_al_limite"] = np.where(tr["tipo"] == K.RETIRO,
                                    (lim - tr["registro"]).dt.total_seconds() / 86400, np.nan)
    return tr


def resumen_casos(c: pd.DataFrame) -> pd.DataFrame:
    """Indicadores por tipo de trámite sobre los atendidos (los rechazados duran poco y sesgan)."""
    filas = []
    for tipo, g in c.groupby("tipo"):
        a = g[g["estado"] == "Atendido"]
        filas.append({
            "tipo": tipo, "tramites": len(g), "atendidos": len(a),
            "archivados": int((g["estado"] == "Archivado").sum()),
            "abiertos": int((g["estado"] == "Abierto").sum()),
            "mediana_dias": a["duracion_dias"].median(),
            "p90_dias": a["duracion_dias"].quantile(0.9),
            "pct_fuera_plazo": a["fuera_plazo"].mean(),
            "pct_reproceso": g["reproceso"].mean(),
            "pct_excepcion": g["excepcion"].mean() if tipo == K.RETIRO else np.nan,
        })
    return pd.DataFrame(filas)


def por_area(ev_t: pd.DataFrame, tramites: pd.DataFrame) -> pd.DataFrame:
    """
    Lo que cada área reporta (su tiempo de atención) contra lo que el trámite
    pasa en ella (espera más atención), en horas hábiles.
    """
    ev = ev_t.merge(tramites[["id_tramite", "tipo"]], on="id_tramite")
    ev = ev[~ev["area"].isin([K.SISTEMA, K.ESTUDIANTE]) & ev["total_h"].notna()]
    ev = ev[~ev["actividad"].isin(K.OBSERVACIONES | {K.ARCHIVAR, K.RECHAZAR_EXT, K.RECHAZAR_DIR})]
    g = ev.groupby(["tipo", "area"])
    res = g.agg(visitas=("total_h", "size"), atencion_media_h=("servicio_h", "mean"),
                en_area_media_h=("total_h", "mean"), en_area_total_h=("total_h", "sum"),
                servicio_total_h=("servicio_h", "sum")).reset_index()
    total = res.groupby("tipo")["en_area_total_h"].transform("sum")
    res["pct_del_tiempo"] = res["en_area_total_h"] / total
    return res


def reparto_tiempo(ev_t: pd.DataFrame, tramites: pd.DataFrame) -> pd.DataFrame:
    """Del tiempo hábil de los trámites atendidos: cuánto es trabajo, espera, estudiante o lote."""
    ok = tramites.loc[tramites["estado"] == "Atendido", ["id_tramite", "tipo"]]
    ev = ev_t.merge(ok, on="id_tramite")
    ev = ev[ev["total_h"].notna()]
    trabajo = ev["servicio_h"].fillna(0)
    estudiante = np.where(ev["area"] == K.ESTUDIANTE, ev["total_h"], 0)
    firma = np.where(ev["actividad"] == K.FIRMAR, ev["total_h"], 0)
    espera = ev["total_h"] - trabajo - estudiante - firma
    d = pd.DataFrame({"tipo": ev["tipo"], "Trabajo de las áreas": trabajo,
                      "Espera en bandeja": espera, "Espera de la firma": firma,
                      "Respuesta del estudiante": estudiante})
    r = d.groupby("tipo").sum()
    return r.div(r.sum(axis=1), axis=0).reset_index().melt("tipo", var_name="componente",
                                                            value_name="pct")


def trabajo_perdido(ev_t: pd.DataFrame, tramites: pd.DataFrame) -> dict:
    """Horas de Dirección y Secretaría gastadas en convalidaciones que terminaron archivadas."""
    arch = tramites.loc[(tramites["estado"] == "Archivado") & (tramites["tipo"] == K.CONVALIDACION),
                        "id_tramite"]
    ev = ev_t[ev_t["id_tramite"].isin(arch)]
    eval_ids = set(ev.loc[ev["actividad"] == K.EVALUAR, "id_tramite"])
    firm_ids = set(ev.loc[ev["actividad"] == K.FIRMAR, "id_tramite"])
    return {
        "archivados": len(arch),
        "archivados_con_evaluacion": len(eval_ids),
        "archivados_con_firma": len(firm_ids),
        "horas_direccion": float(ev.loc[ev["actividad"] == K.EVALUAR, "servicio_h"].sum()),
        "horas_secretaria": float(ev.loc[ev["area"] == K.SECRETARIA, "servicio_h"].sum()),
    }
