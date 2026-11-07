"""
Validación fuera de muestra: se ajusta con lo conocido hasta el corte y se
predice lo que cada cliente hace en los seis meses siguientes.

Se comparan cuatro predicciones de compras: el ritmo histórico sin abandono,
el BG/NBD sin canal, el BG/NBD con el canal como covariable y el MBG/NBD con
canal, que es el que usa el LTV. Para el ingreso se multiplica por el gasto
esperado del Gamma-Gamma.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import rfm as R
from .modelos import ModeloCompras, ModeloGasto, tasa_historica

CORTE = date(2026, 4, 30)
FIN_HOLDOUT = date(2026, 10, 31)

NOMBRES = {"historico": "Ritmo histórico", "bgnbd": "BG/NBD sin canal", "bgnbd_canal": "BG/NBD con canal",
           "mbgnbd_canal": "MBG/NBD con canal"}
ELEGIDO = "mbgnbd_canal"


def _errores(df: pd.DataFrame, col: str) -> dict:
    return {
        "mae_cliente": float(np.mean(np.abs(df[col] - df.compras_real))),
        "error_total_pct": float(df[col].sum() / df.compras_real.sum() - 1),
    }


def validar(con, corte: date = CORTE, fin: date = FIN_HOLDOUT, seed: int = 7) -> dict[str, pd.DataFrame]:
    dias = (fin - corte).days
    cal = R.rfm(con, corte)
    canales = sorted(cal.canal.unique())

    m_sin = ModeloCompras(canales, con_canal=False).ajustar(cal, seed=seed)
    m_bg = ModeloCompras(canales, con_canal=True).ajustar(cal, seed=seed)
    m_canal = ModeloCompras(canales, con_canal=True, modificado=True).ajustar(cal, seed=seed)
    gasto = ModeloGasto().ajustar(cal, seed=seed)

    real = R.compras_en_ventana(con, corte + timedelta(days=1), fin)
    df = cal.merge(real, on="customer_id", how="left").fillna({"compras_real": 0, "ingreso_real": 0.0})
    df["historico"] = tasa_historica(cal, dias)
    df["bgnbd"] = m_sin.compras_esperadas(cal, dias)
    df["bgnbd_canal"] = m_bg.compras_esperadas(cal, dias)
    df["mbgnbd_canal"] = m_canal.compras_esperadas(cal, dias)
    df["gasto_esperado"] = gasto.gasto_esperado(cal)
    df["ingreso_pred"] = df[ELEGIDO] * df.gasto_esperado
    df["p_vivo"] = m_canal.prob_vivo(cal)
    df["p_vivo_bg"] = m_bg.prob_vivo(cal)

    # resumen general y por canal
    general = pd.DataFrame([{"modelo": NOMBRES[c], "clave": c, **_errores(df, c)} for c in NOMBRES])
    general["clientes"] = len(df)
    general["compras_real"] = df.compras_real.sum()
    general["compras_pred"] = [df[c].sum() for c in NOMBRES]

    filas = []
    for canal, d in df.groupby("canal"):
        fila = {"canal": canal, "clientes": len(d), "compras_real": d.compras_real.sum(),
                "ingreso_real": d.ingreso_real.sum(), "ingreso_pred": d.ingreso_pred.sum()}
        for c in NOMBRES:
            fila[f"pred_{c}"] = d[c].sum()
            fila[f"error_{c}"] = d[c].sum() / d.compras_real.sum() - 1
        filas.append(fila)
    por_canal = pd.DataFrame(filas)
    por_canal["error_ingreso"] = por_canal.ingreso_pred / por_canal.ingreso_real - 1

    # por número de compras en calibración: dónde se equivoca el modelo
    df["tramo_frecuencia"] = pd.cut(df.frequency, [-1, 0, 2, 5, 10, 20, 40, np.inf],
                                    labels=["0", "1-2", "3-5", "6-10", "11-20", "21-40", "41+"])
    por_frecuencia = (df.groupby("tramo_frecuencia", observed=True)
                      .agg(clientes=("customer_id", "size"), real=("compras_real", "mean"),
                           historico=("historico", "mean"), bgnbd=("bgnbd", "mean"),
                           bgnbd_canal=("bgnbd_canal", "mean"),
                           mbgnbd_canal=("mbgnbd_canal", "mean")).reset_index())
    por_frecuencia["tramo_frecuencia"] = por_frecuencia.tramo_frecuencia.astype(str)

    # serie semanal del holdout: esperado vs real
    semanas = dias // 7
    acum = [np.zeros(len(cal))]
    for s in range(1, semanas + 1):
        acum.append(m_canal.compras_esperadas(cal, 7 * s))
    esperado = np.diff(np.vstack(acum), axis=0).sum(axis=1)
    sem = R.compras_semanales(con, corte + timedelta(days=1), corte + timedelta(days=7 * semanas),
                              cal.customer_id)
    serie = pd.DataFrame({"semana": np.arange(semanas), "compras_pred": esperado}).merge(
        sem, on="semana", how="left").fillna({"compras_real": 0})
    serie["inicio"] = [corte + timedelta(days=1 + 7 * int(s)) for s in serie.semana]

    # calibración de P(vivo) contra lo que de verdad pasó (solo posible con datos simulados)
    vivos = con.execute("""
        SELECT id_cliente AS customer_id, (fecha_fin_real IS NULL OR fecha_fin_real > ?) AS vivo_real
        FROM aux_clientes
    """, [corte]).df()
    pv = df[["customer_id", "frequency", "p_vivo", "p_vivo_bg"]].merge(vivos, on="customer_id")
    calib = []
    for modelo, col in (("BG/NBD con canal", "p_vivo_bg"), ("MBG/NBD con canal", "p_vivo")):
        d = pv.assign(decil=pd.qcut(pv[col].rank(method="first"), 10, labels=False) + 1)
        g = d.groupby("decil").agg(p_vivo=(col, "mean"), vivo_real=("vivo_real", "mean"),
                                   clientes=("customer_id", "size")).reset_index()
        calib.append(g.assign(modelo=modelo))
    calib = pd.concat(calib, ignore_index=True)
    una = pv[pv.frequency == 0]

    resumen = pd.DataFrame([{
        "corte": corte, "fin": fin, "dias": dias, "clientes": len(cal),
        "brier_bg": float(np.mean((pv.p_vivo_bg - pv.vivo_real) ** 2)),
        "brier_mbg": float(np.mean((pv.p_vivo - pv.vivo_real) ** 2)),
        "una_compra_clientes": len(una), "una_compra_vivos": float(una.vivo_real.mean()),
        "una_compra_p_bg": float(una.p_vivo_bg.mean()), "una_compra_p_mbg": float(una.p_vivo.mean()),
    }])
    return {"val_resumen": resumen, "val_general": general, "val_canal": por_canal,
            "val_frecuencia": por_frecuencia, "val_semanal": serie, "val_p_vivo": calib}
