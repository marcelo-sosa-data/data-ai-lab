"""
Conformidad: qué tanto sigue el log al proceso que manda el reglamento.

El modelo de cada trámite se escribe como árbol de proceso de PM4Py y se
alinea contra cada traza atendida. Aparte, cuatro controles en reglas
simples dicen qué desvío tiene cada caso, que es lo que se le puede pedir
corregir a un área.
"""

from __future__ import annotations

import os

os.environ.setdefault("PM4PY_SHOW_PROGRESS_BAR", "False")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pm4py  # noqa: E402

from . import catalogos as K  # noqa: E402
from .descubrimiento import a_pm4py  # noqa: E402

REGLAMENTO = {
    K.CONVALIDACION: f"""->( '{K.REGISTRAR}',
        *( ->( *('{K.REVISAR_EXP}', ->('{K.OBSERVAR_EXP}', '{K.SUBSANAR}')), '{K.EVALUAR}'),
           ->('{K.OBSERVAR_SIL}', '{K.SUBSANAR}') ),
        '{K.EMITIR}', '{K.FIRMAR}',
        *('{K.VERIFICAR_PAGO}', ->('{K.OBSERVAR_PAGO}', '{K.PAGAR}')),
        '{K.REGISTRAR_CONV}', '{K.NOTIFICAR}' )""",
    K.RETIRO: f"""->( '{K.REGISTRAR}',
        *('{K.REVISAR_SOL}', ->('{K.OBSERVAR_SOL}', '{K.SUBSANAR}')),
        '{K.VISTO_BUENO}',
        *('{K.VERIFICAR_DEUDA}', ->('{K.OBSERVAR_DEUDA}', '{K.PAGAR_DEUDA}')),
        X( tau, ->('{K.DEVOLVER_PLAZO}', '{K.EMITIR_EXCEPCION}', '{K.FIRMAR}') ),
        '{K.APROBAR_RETIRO}', '{K.NOTIFICAR}' )""",
}

CONTROLES = {
    "sin_pago": "Convalidación registrada sin pago verificado antes",
    "pago_despues": "Pago verificado después de registrar la convalidación",
    "sin_revision": "Dirección evaluó sin revisión previa de Secretaría",
    "sin_visto_bueno": "Retiro aprobado sin visto bueno de Dirección",
}


def red_reglamento(tipo: str):
    arbol = pm4py.parse_process_tree(" ".join(REGLAMENTO[tipo].split()))
    return pm4py.convert_to_petri_net(arbol)


def alinear(eventos: pd.DataFrame, tramites: pd.DataFrame) -> pd.DataFrame:
    """Fitness de alineamiento de cada trámite atendido contra el modelo del reglamento."""
    filas = []
    for tipo in REGLAMENTO:
        ids = tramites.loc[(tramites["tipo"] == tipo) & (tramites["estado"] == "Atendido"), "id_tramite"]
        ev = eventos[eventos["id_tramite"].isin(ids)]
        if ev.empty:
            continue
        df = a_pm4py(ev)
        net, im, fm = red_reglamento(tipo)
        al = pm4py.conformance_diagnostics_alignments(df, net, im, fm, multi_processing=False)
        casos = df.groupby("case:concept:name", sort=False).size().index
        for caso, a in zip(casos, al):
            movs = [m for m in a["alignment"] if m[0] != m[1] and ">>" in m]
            sobran = [m[0] for m in movs if m[1] == ">>"]
            faltan = [m[1] for m in movs if m[0] == ">>" and m[1] is not None]
            filas.append({"id_tramite": caso, "tipo": tipo, "fitness": a["fitness"],
                          "sobra": ", ".join(sorted(set(sobran))), "falta": ", ".join(sorted(set(faltan)))})
    return pd.DataFrame(filas)


def controles(eventos: pd.DataFrame, tramites: pd.DataFrame) -> pd.DataFrame:
    """Un indicador por control y por trámite, sobre los que llegaron a la actividad que se controla."""
    ev = eventos.sort_values(["id_tramite", "orden"])
    sig = ev.groupby("id_tramite")["actividad"].shift(-1)
    pago_ok = ev[(ev["actividad"] == K.VERIFICAR_PAGO) & (sig != K.OBSERVAR_PAGO)]
    primer_pago = pago_ok.groupby("id_tramite")["fin"].min()
    registro = ev[ev["actividad"] == K.REGISTRAR_CONV].groupby("id_tramite")["fin"].min()
    revision = ev[ev["actividad"] == K.REVISAR_EXP].groupby("id_tramite")["fin"].min()
    evaluacion = ev[ev["actividad"] == K.EVALUAR].groupby("id_tramite")["fin"].min()
    visto = set(ev.loc[ev["actividad"] == K.VISTO_BUENO, "id_tramite"])
    aprobado = set(ev.loc[ev["actividad"] == K.APROBAR_RETIRO, "id_tramite"])

    t = tramites[["id_tramite", "tipo"]].copy()
    r = _fechas(registro, t)
    p = _fechas(primer_pago, t)
    t["sin_pago"] = (p.isna() | (p > r)).astype(float).where(r.notna())
    t["pago_despues"] = (p.notna() & (p > r)).astype(float).where(r.notna())
    e = _fechas(evaluacion, t)
    v = _fechas(revision, t)
    t["sin_revision"] = (v.isna() | (v > e)).astype(float).where(e.notna())
    t["sin_visto_bueno"] = (~t["id_tramite"].isin(visto)).astype(float).where(t["id_tramite"].isin(aprobado))
    return t


def _fechas(serie: pd.Series, t: pd.DataFrame) -> pd.Series:
    return pd.Series(pd.to_datetime(serie.reindex(t["id_tramite"]).to_numpy()), index=t.index)


def resumen_controles(c: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for k, desc in CONTROLES.items():
        s = c[k].dropna()
        filas.append({"control": desc, "evaluados": len(s), "casos": int(s.sum()),
                      "pct": s.mean() if len(s) else np.nan})
    return pd.DataFrame(filas)
