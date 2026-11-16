"""
Evaluación fuera de muestra: el modelo se ajusta con lo conocido hasta un corte y
estima cada promoción que se hizo después. Se compara contra la estimación de la
planilla (AS IS) y contra el margen incremental real, que existe solo porque los
datos son simulados.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import asis
from .consultas import Matrices, promociones, verdad_promos
from .simulador import DESCUENTOS, Escenario, Simulador

PROB_APROBAR = 0.6  # el comité TO BE aprueba si la promoción gana margen con 60% o más de probabilidad


def evaluar_promos(con, m: Matrices, sim: Simulador, corte: pd.Timestamp) -> pd.DataFrame:
    """Una fila por promoción posterior al corte con AS IS, TO BE, recomendación y realidad."""
    pr = promociones(con)
    pr = pr[pd.to_datetime(pr.inicio) >= corte].copy()
    est = asis.estimar(con).set_index("id_promo")
    verdad = verdad_promos(con)
    real = verdad[verdad.es_real].set_index("id_promo")

    filas = []
    for r in pr.itertuples():
        esc = Escenario(r.id_sku, pd.Timestamp(r.inicio), int(r.semanas), float(r.descuento),
                        bool(r.encarte), float(r.aporte_proveedor_pct))
        tobe = sim.resumir(esc)
        rec = sim.recomendar(esc)
        v_rec = verdad[(verdad.id_promo == r.id_promo) & np.isclose(verdad.descuento, rec["descuento"])]
        a = est.reindex([r.id_promo]).iloc[0]
        filas.append(dict(
            id_promo=r.id_promo, id_sku=r.id_sku, descripcion=r.descripcion, categoria=r.categoria,
            inicio=pd.Timestamp(r.inicio), semanas=int(r.semanas), descuento=float(r.descuento),
            encarte=bool(r.encarte), aporte_pct=float(r.aporte_proveedor_pct),
            asis_margen=float(a.margen_incremental_asis), asis_unid=float(a.unid_incrementales_asis),
            asis_venta=float(a.venta_incremental_asis),
            asis_aprueba=True,  # en el proceso actual se ejecutó todo el calendario
            tobe_margen=tobe["margen_media"], tobe_p05=tobe["margen_p05"], tobe_p95=tobe["margen_p95"],
            tobe_prob=tobe["prob_gana"], tobe_unid=tobe["unid_propias"],
            tobe_canib=tobe["unid_canibalizadas"], tobe_post=tobe["unid_post"],
            tobe_aprueba=tobe["prob_gana"] >= PROB_APROBAR,
            rec_descuento=rec["descuento"], rec_margen=rec["margen_media"],
            real_margen=float(real.loc[r.id_promo, "margen_incremental"]),
            real_venta=float(real.loc[r.id_promo, "venta_incremental"]),
            real_unid=float(real.loc[r.id_promo, "unid_propias"]),
            real_canib=float(real.loc[r.id_promo, "unid_canibalizadas"]),
            real_post=float(real.loc[r.id_promo, "unid_post"]),
            real_margen_rec=float(v_rec.margen_incremental.iloc[0]) if len(v_rec) else 0.0,
        ))
    return pd.DataFrame(filas)


def resumen(ev: pd.DataFrame) -> pd.DataFrame:
    """Indicadores AS IS frente a TO BE sobre las promociones del periodo de prueba."""
    n = len(ev)
    neg = ev.real_margen < 0

    def mae(col):
        return float((ev[col] - ev.real_margen).abs().mean())

    def signo(col):
        return float(((ev[col] > 0) == (ev.real_margen > 0)).mean())

    def err_unid(col):
        return float((ev[col] - ev.real_unid).abs().sum() / ev.real_unid.abs().sum())

    filas = [
        dict(indicador="promociones evaluadas", asis=n, tobe=n),
        dict(indicador="error absoluto medio del margen incremental (S/)", asis=mae("asis_margen"),
             tobe=mae("tobe_margen")),
        dict(indicador="aciertos en el signo del margen", asis=signo("asis_margen"), tobe=signo("tobe_margen")),
        dict(indicador="error en unidades incrementales del producto (WAPE)", asis=err_unid("asis_unid"),
             tobe=err_unid("tobe_unid")),
        dict(indicador="promociones aprobadas", asis=int(ev.asis_aprueba.sum()), tobe=int(ev.tobe_aprueba.sum())),
        dict(indicador="aprobadas que perdieron margen", asis=int((ev.asis_aprueba & neg).sum()),
             tobe=int((ev.tobe_aprueba & neg).sum())),
        dict(indicador="margen incremental real de lo aprobado (S/)",
             asis=float(ev.real_margen[ev.asis_aprueba].sum()), tobe=float(ev.real_margen[ev.tobe_aprueba].sum())),
        dict(indicador="margen incremental real con el descuento recomendado (S/)",
             asis=float(ev.real_margen[ev.asis_aprueba].sum()), tobe=float(ev.real_margen_rec.sum())),
        dict(indicador="venta incremental real de lo aprobado (S/)",
             asis=float(ev.real_venta[ev.asis_aprueba].sum()), tobe=float(ev.real_venta[ev.tobe_aprueba].sum())),
    ]
    return pd.DataFrame(filas)


def recuperacion(post: dict, verdad_sku: pd.DataFrame, skus: pd.DataFrame) -> pd.DataFrame:
    """Elasticidad estimada por producto frente a la verdadera (formato Super)."""
    e = post["e"]
    lo, hi = np.percentile(e, [5, 95], axis=0)
    df = skus[["id_sku", "descripcion", "categoria", "marca_propia"]].copy()
    df["elasticidad"] = e.mean(0)
    df["p05"], df["p95"] = lo, hi
    df = df.merge(verdad_sku[["id_sku", "elasticidad"]].rename(columns={"elasticidad": "verdadera"}), on="id_sku")
    df["cubre"] = (df.verdadera >= df.p05) & (df.verdadera <= df.p95)
    return df


__all__ = ["evaluar_promos", "resumen", "recuperacion", "DESCUENTOS", "PROB_APROBAR"]
