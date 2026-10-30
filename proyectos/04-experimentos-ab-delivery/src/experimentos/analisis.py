"""
Lectura completa de un experimento: SRM, todas las métricas (con y sin CUPED),
segmentos con corrección por comparaciones múltiples, efecto por semana desde la
exposición, trayectoria secuencial y la decisión.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .catalogo import METRICAS, Experimento
from .decision import Decision, decidir
from .estadistica import Comparacion, benjamini_hochberg, comparar_medias, comparar_ratio, cuped, srm
from .metricas import acumulado_diario, tabla_usuarios
from .secuencial import trayectoria

SEGMENTOS = {"region": ["Lima", "provincia"], "tipo_usuario": ["recurrente", "nuevo"],
             "plataforma": ["ios", "android"]}


@dataclass
class Lectura:
    experimento: Experimento
    usuarios: pd.DataFrame
    p_srm: float
    srm_por_version: pd.DataFrame
    metricas: pd.DataFrame
    lecturas: dict[str, Comparacion]
    segmentos: pd.DataFrame
    semanas: pd.DataFrame
    secuencial: pd.DataFrame
    decision: Decision

    @property
    def n_control(self) -> int:
        return int((~self.usuarios.tratamiento).sum())

    @property
    def n_tratamiento(self) -> int:
        return int(self.usuarios.tratamiento.sum())


def leer_metrica(u: pd.DataFrame, metrica: str, con_cuped: bool = True) -> Comparacion:
    m = METRICAS[metrica]
    t = u.tratamiento.to_numpy()
    if m["tipo"] == "ratio":
        return comparar_ratio(u[m["num"]].to_numpy(), u[m["den"]].to_numpy(), t)
    if con_cuped:
        return cuped(u[metrica].to_numpy(), u[f"{metrica}_pre"].to_numpy(), t)
    return comparar_medias(u[metrica].to_numpy(), t)


def tabla_metricas(u: pd.DataFrame, exp: Experimento) -> tuple[pd.DataFrame, dict[str, Comparacion]]:
    rol = {exp.primaria: "primaria"} | {g.metrica: "guardrail" for g in exp.guardrails}
    filas, lecturas = [], {}
    for met, info in METRICAS.items():
        variantes = [("delta", leer_metrica(u, met))] if info["tipo"] == "ratio" else \
            [("welch", leer_metrica(u, met, False)), ("cuped", leer_metrica(u, met, True))]
        for metodo, c in variantes:
            filas.append({"metrica": met, "nombre": info["nombre"], "rol": rol.get(met, "secundaria"),
                          **c.a_dict(), "metodo": metodo})
        lecturas[met] = variantes[-1][1]
    orden = {"primaria": 0, "guardrail": 1, "secundaria": 2}
    df = pd.DataFrame(filas)
    df = df.sort_values(["rol", "metrica"], key=lambda s: s.map(orden) if s.name == "rol" else s, kind="stable")
    return df.reset_index(drop=True), lecturas


def tabla_segmentos(u: pd.DataFrame, metrica: str) -> pd.DataFrame:
    u = u.assign(tipo_usuario=np.where(u.recurrente, "recurrente", "nuevo"))
    filas = []
    for dim, valores in SEGMENTOS.items():
        for v in valores:
            s = u[u[dim] == v]
            if s.tratamiento.sum() < 50 or (~s.tratamiento).sum() < 50:
                continue
            c = leer_metrica(s, metrica)
            filas.append({"dimension": dim, "segmento": v, **c.a_dict()})
    df = pd.DataFrame(filas)
    if len(df):
        df["q_valor"] = benjamini_hochberg(df.p_valor.to_numpy())
    return df


def srm_por_version(u: pd.DataFrame, reparto: float) -> pd.DataFrame:
    """Dónde está el desbalance: si el SRM vive en un segmento, apunta al bug."""
    g = u.groupby("version_app").tratamiento.agg(n="size", tratamiento="sum").reset_index()
    g["control"] = g.n - g.tratamiento
    g["pct_tratamiento"] = g.tratamiento / g.n
    g["p_srm"] = [srm(int(r.control), int(r.tratamiento), reparto) for r in g.itertuples()]
    return g[["version_app", "control", "tratamiento", "pct_tratamiento", "p_srm"]]


def efecto_por_semana(u: pd.DataFrame, dias: pd.DatetimeIndex, acum: np.ndarray, metrica: str,
                      semanas: int = 4) -> pd.DataFrame:
    """
    Efecto en la semana 1, 2, ... desde la exposición de cada usuario. Si cae con las
    semanas es novedad: lo que se mide en un mes no es lo que queda.
    """
    ex = ((u.fecha_exposicion - dias[0]).dt.days).to_numpy()
    t = u.tratamiento.to_numpy()
    x = u[f"{metrica}_pre"].to_numpy(float)
    filas = []
    for w in range(semanas):
        fin = ex + 7 * w + 6
        ok = fin <= len(dias) - 1
        if ok.sum() < 200:
            continue
        idx = np.where(ok)[0]
        hasta = acum[idx, fin[idx]]
        desde = np.where(ex[idx] + 7 * w - 1 >= 0, acum[idx, np.maximum(ex[idx] + 7 * w - 1, 0)], 0.0)
        c = cuped(hasta - desde, x[idx], t[idx])
        filas.append({"semana": str(w + 1), **c.a_dict()})
    # todo lo que viene después de la primera semana, para quien la tuvo completa
    ok = ex + 6 < len(dias) - 1
    if ok.sum() >= 200:
        idx = np.where(ok)[0]
        c = cuped(acum[idx, -1] - acum[idx, ex[idx] + 6], x[idx], t[idx])
        filas.append({"semana": "2+", **c.a_dict()})
    return pd.DataFrame(filas)


def leer(con, exp: Experimento) -> Lectura:
    u = tabla_usuarios(con, exp.id, exp.inicio, exp.fin)
    n_t = int(u.tratamiento.sum())
    n_c = len(u) - n_t
    p_srm = srm(n_c, n_t, exp.reparto)
    met, lecturas = tabla_metricas(u, exp)
    seg = tabla_segmentos(u, exp.primaria)

    dias, acum, expo = acumulado_diario(con, exp.id, u, exp.inicio, exp.fin, exp.primaria)
    sem = efecto_por_semana(u, dias, acum, exp.primaria)
    tray = trayectoria(dias, acum, expo, u.tratamiento.to_numpy(), u[f"{exp.primaria}_pre"].to_numpy(float))
    dec = decidir(exp, p_srm, lecturas, n_c, n_t, sem)
    return Lectura(exp, u, p_srm, srm_por_version(u, exp.reparto), met, lecturas, seg, sem, tray, dec)
