"""
Validación de la simulación y comparación de escenarios.

1. Se estiman los parámetros con lo registrado de enero a junio y se simula
   el proceso actual sobre lo registrado de julio a octubre. Lo simulado se
   compara con lo observado en esos mismos trámites.
2. Cada escenario se simula sobre los mismos trámites. Su efecto es el
   cambio relativo contra la simulación del proceso actual, y se aplica a lo
   observado: así el sesgo que tenga la simulación se cancela en buena parte.
3. Como los datos son sintéticos, el generador puede correr los mismos
   trámites con las reglas de cada escenario. Eso dice cuánto se equivoca
   la simulación al estimar el efecto. Con datos reales este paso no existe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from . import catalogos as K
from . import simulacion as S
from .calendario import HORAS_DIA, a_habiles

METRICAS = ["mediana_dias", "p90_dias", "pct_fuera_plazo", "pct_excepcion"]


def observado(casos: pd.DataFrame) -> pd.DataFrame:
    """Los mismos indicadores que da la simulación, medidos en el log."""
    return S.indicadores(casos)


def periodo_prueba(tramites: pd.DataFrame) -> pd.DataFrame:
    return tramites[tramites["registro"].between(K.INICIO_PRUEBA, K.FIN_PRUEBA)].copy()


def correr_escenarios(par: S.Parametros, prueba: pd.DataFrame, replicas: int = 30,
                      seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Indicadores de cada escenario por réplica y extras de carga de trabajo."""
    ind, extras = [], []
    for clave, (nombre, reglas) in K.ESCENARIOS.items():
        df = S.simular(par, prueba, reglas, actual=(clave == "actual"), replicas=replicas, seed=seed)
        i = S.indicadores(df, ["replica"])
        i.insert(0, "escenario", clave)
        ind.append(i)
        conv, ret = df[df["tipo"] == K.CONVALIDACION], df[df["tipo"] == K.RETIRO]
        arch = conv[conv["estado"] == "Archivado"]
        extras.append({
            "escenario": clave, "nombre": nombre,
            "revisiones_secretaria_por_conv": conv["revisiones"].mean(),
            "evaluaciones_por_conv": conv["evaluaciones"].mean(),
            "evaluaciones_en_archivados": arch["evaluaciones"].sum() / replicas,
            "archivados_tras_firma": arch.get("archivado_tras_firma", pd.Series(dtype=bool)).fillna(False).sum() / replicas,
            "pct_retiros_por_direccion": ret["direccion"].astype(float).mean(),
        })
    return pd.concat(ind, ignore_index=True), pd.DataFrame(extras)


def comparar(ind: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """
    Por escenario y tipo: promedio simulado, rango 5-95%, estimado y efecto.
    estimado = observado x (simulado del escenario / simulado del actual).
    """
    res = []
    for esc, g in ind.groupby("escenario", sort=False):
        r = S.resumir_replicas(g)
        r.insert(0, "escenario", esc)
        res.append(r)
    res = pd.concat(res, ignore_index=True)
    base = res[res["escenario"] == "actual"].set_index("tipo")
    o = obs.set_index("tipo")
    for m in METRICAS:
        res[f"estimado_{m}"] = res["tipo"].map(o[m]) * res[m] / res["tipo"].map(base[m])
        res[f"efecto_{m}"] = res[f"estimado_{m}"] - res["tipo"].map(o[m])
    res["nombre"] = res["escenario"].map({k: v[0] for k, v in K.ESCENARIOS.items()})
    return res


def validacion(res: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    sim = res[res["escenario"] == "actual"].set_index("tipo")
    o = obs.set_index("tipo")
    filas = []
    for tipo in o.index:
        for m in METRICAS:
            if pd.isna(o.loc[tipo, m]):
                continue
            filas.append({"tipo": tipo, "metrica": m, "observado": o.loc[tipo, m],
                          "simulado": sim.loc[tipo, m], "p05": sim.loc[tipo, f"{m}_p05"],
                          "p95": sim.loc[tipo, f"{m}_p95"],
                          "error_relativo": (sim.loc[tipo, m] / o.loc[tipo, m] - 1)
                          if o.loc[tipo, m] else float("nan")})
    return pd.DataFrame(filas)


# --------------------------------------------------------------------------
# Verdad del generador
# --------------------------------------------------------------------------

def _generador(raiz: Path):
    sys.path.insert(0, str(raiz / "datos"))
    import generar_datos  # noqa: PLC0415
    return generar_datos


def verdad(casos_verdad: pd.DataFrame, ids_prueba, raiz: Path, seed: int = 16) -> pd.DataFrame:
    """Corre el generador con las reglas de cada escenario sobre los mismos trámites."""
    gen = _generador(raiz)
    casos = casos_verdad[["id_tramite", "tipo", "registro", "n_cursos", "origen", "carrera", "sede",
                          "becado", "codigo_alumno", "nombre_alumno"]].copy()
    casos["origen"] = casos["origen"].where(casos["origen"].notna(), None)
    filas = []
    for clave, (nombre, reglas) in K.ESCENARIOS.items():
        ev, fines = gen.simular(casos, reglas, seed)
        d = casos.merge(fines, on="id_tramite")
        d = d[d["id_tramite"].isin(set(ids_prueba))].copy()
        d["estado"] = d["resultado"]
        d["duracion_dias"] = (d["fin"] - d["registro"]).dt.total_seconds() / 86400
        d["dias_habiles"] = (a_habiles(d["fin"]) - a_habiles(d["registro"])) / HORAS_DIA
        d["fuera_plazo"] = d["dias_habiles"] > d["tipo"].map(K.PLAZO_DIAS)
        d["excepcion"] = d["id_tramite"].isin(set(ev.loc[ev["actividad"] == K.DEVOLVER_PLAZO, "id_tramite"]))
        i = S.indicadores(d)
        i.insert(0, "escenario", clave)
        i["nombre"] = nombre
        vb = ev[(ev["actividad"] == K.VISTO_BUENO) & ev["id_tramite"].isin(set(ids_prueba))]
        i["visto_bueno"] = len(vb)
        filas.append(i)
    return pd.concat(filas, ignore_index=True)


def contra_verdad(res: pd.DataFrame, ver: pd.DataFrame) -> pd.DataFrame:
    """Efecto de cada escenario según la simulación y según el generador."""
    v = ver.set_index(["escenario", "tipo"])
    base = ver[ver["escenario"] == "actual"].set_index("tipo")
    filas = []
    for r in res.itertuples():
        for m in METRICAS:
            if pd.isna(getattr(r, m)):
                continue
            real = v.loc[(r.escenario, r.tipo), m]
            filas.append({"escenario": r.escenario, "tipo": r.tipo, "metrica": m,
                          "estimado": getattr(r, f"estimado_{m}"), "real": real,
                          "efecto_estimado": getattr(r, f"efecto_{m}"),
                          "efecto_real": real - base.loc[r.tipo, m]})
    return pd.DataFrame(filas)
