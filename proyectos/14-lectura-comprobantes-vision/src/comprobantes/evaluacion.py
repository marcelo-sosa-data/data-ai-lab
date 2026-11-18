"""
Mide la lectura campo por campo, el ruteo y el proceso completo contra la verdad.

La calibración del umbral usa setiembre y todas las cifras de resultado son
de octubre, que el umbral no vio.
"""

from __future__ import annotations

import json

import pandas as pd

from .esquema import CAMPOS, Comprobante, comparar
from .procesar import rutear
from .regla_actual import SE_VE_AL_CIERRE, TIPO_CAMBIO, deteccion_as_is, fecha_cierre
from .ruteo import MOTIVO_DE_ANOMALIA

META_ERROR_APROBADOS = 0.01   # máximo 1 de cada 100 aprobados solos con algún campo mal
PERCENTILES = [0.0, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]


def _verdad_dict(r: dict) -> dict:
    return {k: (None if pd.isna(r[k]) else r[k]) for k in CAMPOS}


def aciertos(lecturas: pd.DataFrame, verdad: pd.DataFrame) -> pd.DataFrame:
    """Una fila por comprobante con True/False por campo y el detalle de cómo llegó."""
    v = verdad.set_index("doc_id")
    filas = []
    for r in lecturas.itertuples():
        comp = Comprobante.model_validate_json(r.comprobante)
        fila = v.loc[r.doc_id].to_dict()
        fila["fecha_emision"] = pd.Timestamp(fila["fecha_emision"]).date()
        ok = comparar(comp, _verdad_dict(fila))
        filas.append({"doc_id": r.doc_id, **ok, "doc_correcto": all(ok.values()),
                      "captura": fila["captura"], "plantilla": fila["plantilla"],
                      "mes": pd.Timestamp(fila["fecha_recepcion"]).month})
    return pd.DataFrame(filas)


def exactitud_por_campo(ac: pd.DataFrame, por: str | None = None) -> pd.DataFrame:
    if por is None:
        return ac[CAMPOS].mean().rename("exactitud").to_frame()
    return ac.groupby(por)[CAMPOS + ["doc_correcto"]].mean()


def metricas_ruteo(dec: pd.DataFrame, ac: pd.DataFrame, verdad: pd.DataFrame) -> dict:
    d = dec.merge(ac[["doc_id", "doc_correcto"]], on="doc_id").merge(
        verdad[["doc_id", "anomalia"]], on="doc_id")
    apr = d[d["destino"] == "aprobado"]
    rev = d[d["destino"] == "revision"]
    errores_aprob = int((~apr["doc_correcto"]).sum())
    anomalias_aprob = int(apr["anomalia"].notna().sum())
    return {
        "comprobantes": len(d),
        "aprobados": len(apr),
        "pct_aprobados": len(apr) / len(d) if len(d) else 0.0,
        "aprobados_con_error": errores_aprob,
        "tasa_error_aprobados": errores_aprob / len(apr) if len(apr) else 0.0,
        "aprobados_con_anomalia": anomalias_aprob,
        "en_revision": len(rev),
        "revision_sin_motivo_real": int((rev["doc_correcto"] & rev["anomalia"].isna()).sum()),
        "docs_con_error_lectura": int((~d["doc_correcto"]).sum()),
    }


def _detectada(anomalia: str, motivos: str, tras_correccion: str) -> bool:
    """El error sale con su motivo al leer o cuando se vuelven a correr los controles tras corregir."""
    motivo = MOTIVO_DE_ANOMALIA[anomalia]
    return motivo in json.loads(motivos) or motivo in json.loads(tras_correccion or "[]")


def deteccion_por_anomalia(dec: pd.DataFrame, verdad: pd.DataFrame) -> pd.DataFrame:
    d = dec.merge(verdad[["doc_id", "anomalia"]], on="doc_id")
    d = d[d["anomalia"].notna()].copy()
    d["motivo_correcto"] = [_detectada(a, m, t) for a, m, t in zip(d["anomalia"], d["motivos"], d["motivos_tras_correccion"])]
    d["motivo_al_leer"] = [MOTIVO_DE_ANOMALIA[a] in json.loads(m) for a, m in zip(d["anomalia"], d["motivos"])]
    d["en_revision"] = d["destino"] == "revision"
    return (d.groupby("anomalia").agg(n=("doc_id", "size"), a_revision=("en_revision", "sum"),
                                      motivo_al_leer=("motivo_al_leer", "sum"),
                                      con_motivo=("motivo_correcto", "sum"))
            .sort_values("n", ascending=False))


def umbrales_por_campo(lecturas: pd.DataFrame, ac: pd.DataFrame, q: float) -> dict[str, float]:
    """Umbral de cada campo = percentil q de la confianza de sus lecturas correctas."""
    conf = pd.DataFrame([json.loads(x) for x in lecturas["confianza"]], index=lecturas["doc_id"])
    ok = ac.set_index("doc_id").loc[conf.index]
    return {k: float(conf.loc[ok[k], k].dropna().quantile(q)) if q > 0 else 0.0
            for k in CAMPOS if k in conf}


def curva_umbral(lecturas, recepcion, ctx, verdad, ac) -> pd.DataFrame:
    filas = []
    for q in PERCENTILES:
        umbral = umbrales_por_campo(lecturas, ac, q)
        dec = rutear(lecturas, recepcion, ctx, umbral, verdad)
        m = metricas_ruteo(dec, ac[ac["doc_id"].isin(dec["doc_id"])], verdad)
        filas.append({"percentil": q, "pct_aprobados": m["pct_aprobados"],
                      "tasa_error_aprobados": m["tasa_error_aprobados"],
                      "aprobados_con_error": m["aprobados_con_error"], "umbrales": json.dumps(umbral)})
    return pd.DataFrame(filas)


def elegir_umbral(curva: pd.DataFrame, meta: float = META_ERROR_APROBADOS) -> tuple[float, dict]:
    """El percentil más bajo (el que más aprueba) que cumple la meta de error en calibración."""
    ok = curva[curva["tasa_error_aprobados"] <= meta]
    fila = ok.loc[ok["percentil"].idxmin()] if len(ok) else curva.loc[curva["percentil"].idxmax()]
    return float(fila["percentil"]), json.loads(fila["umbrales"])


def as_is_vs_to_be(dec: pd.DataFrame, verdad: pd.DataFrame, ac: pd.DataFrame) -> dict:
    """Indicadores del proceso actual y del rediseñado sobre los mismos comprobantes."""
    asis = deteccion_as_is(verdad)
    d = dec.merge(verdad[["doc_id", "anomalia", "fecha_recepcion", "fecha_vencimiento"]], on="doc_id")
    d = d[d["anomalia"].notna()].copy()
    d["en_bandeja"] = [dst == "revision" and _detectada(a, m, t)
                       for a, m, t, dst in zip(d["anomalia"], d["motivos"], d["motivos_tras_correccion"], d["destino"])]
    # TO BE: lo que no atrapa la bandeja todavía puede salir al cierre, como hoy
    recep = pd.to_datetime(d["fecha_recepcion"]).dt.date
    vence = pd.to_datetime(d["fecha_vencimiento"]).dt.date
    det, pagado = [], []
    for b, a, r, vto in zip(d["en_bandeja"], d["anomalia"], recep, vence):
        if b:
            det.append(r)
            pagado.append(False)
        elif a in SE_VE_AL_CIERRE:
            det.append(fecha_cierre(r))
            pagado.append(vto < fecha_cierre(r))
        else:
            det.append(None)
            pagado.append(True)
    d["fecha_deteccion"], d["pagado_antes"] = det, pagado
    d["dias_a_deteccion"] = [(x - r).days if x else None for x, r in zip(det, recep)]
    tobe = d.merge(verdad[["doc_id", "total", "moneda"]], on="doc_id")
    tobe["monto_soles"] = tobe["total"] * tobe["moneda"].map({"PEN": 1.0, "USD": TIPO_CAMBIO})

    m = metricas_ruteo(dec, ac, verdad)
    return {
        "comprobantes": m["comprobantes"],
        "con_anomalia": len(asis),
        "as_is": {
            "pct_digitado": 1.0,
            "detectadas_antes_de_pagar": int((~asis["pagado_antes"]).sum()),
            "dias_a_deteccion": float(asis["dias_a_deteccion"].dropna().mean()),
            "nunca_detectadas": int((~asis["detectado"]).sum()),
            "pagadas_sin_detectar": int(asis["pagado_antes"].sum()),
            "monto_pagado_sin_detectar": float(asis.loc[asis["pagado_antes"], "monto_soles"].sum()),
        },
        "to_be": {
            "pct_digitado": 1 - m["pct_aprobados"],
            "detectadas_en_recepcion": int(d["en_bandeja"].sum()),
            "detectadas_antes_de_pagar": int((~tobe["pagado_antes"]).sum()),
            "dias_a_deteccion": float(pd.Series(d["dias_a_deteccion"]).dropna().mean()),
            "nunca_detectadas": int(sum(x is None for x in det)),
            "pagadas_sin_detectar": int(tobe["pagado_antes"].sum()),
            "monto_pagado_sin_detectar": float(tobe.loc[tobe["pagado_antes"], "monto_soles"].sum()),
            "tasa_error_aprobados": m["tasa_error_aprobados"],
            "aprobados_con_error": m["aprobados_con_error"],
        },
    }
