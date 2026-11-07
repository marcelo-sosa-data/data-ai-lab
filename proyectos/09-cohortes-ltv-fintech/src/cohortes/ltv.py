"""
Valor de vida por canal y valor de la base actual.

LTV de un cliente activado de cada canal, mes a mes:

    LTV(m) = p_ingreso * [ ingreso del primer día
                           + sum_{j<=m} (compras esperadas en el mes j) * gasto por compra / (1 + d)^j ]

p_ingreso es la parte de los activados que llega a tener un día con ingreso
(el modelo empieza a contar desde ahí) y d es el costo de capital mensual.
El CAC es el de los últimos seis meses de cohortes, que es el que se está pagando hoy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import consultas as q
from . import rfm as R
from .modelos import ModeloCompras, ModeloGasto

DIAS_MES = 30.4
TASA_MENSUAL = 0.01  # ~12.7% anual
MESES = 24
SEGMENTOS = ["Valiosos activos", "Valiosos en riesgo", "Activos", "En duda", "Probablemente perdidos"]


def descontar(incrementos: np.ndarray, tasa: float = TASA_MENSUAL) -> np.ndarray:
    """Valor presente acumulado de flujos mensuales; el primero cae en el mes 1."""
    j = np.arange(1, len(incrementos) + 1)
    return np.cumsum(np.asarray(incrementos) / (1 + tasa) ** j)


def mes_payback(curva: pd.Series, cac: float) -> float:
    """Primer mes en que la curva acumulada cubre el CAC (NaN si no llega)."""
    ok = curva[curva >= cac]
    return float(ok.index[0]) if len(ok) else np.nan


def curvas_nuevo_cliente(compras: ModeloCompras, gasto: ModeloGasto, inicio: pd.DataFrame,
                         meses: int = MESES, tasa: float = TASA_MENSUAL) -> pd.DataFrame:
    """LTV acumulado por mes de vida para un cliente activado de cada canal."""
    dias = [round(DIAS_MES * m) for m in range(1, meses + 1)]
    nc = compras.nuevo_cliente(dias)
    g = gasto.gasto_nuevo()
    ini = inicio.set_index("canal")
    filas = []
    for canal, d in nc.groupby("canal"):
        acum = d.sort_values("dias").compras.to_numpy()
        inc = np.diff(np.concatenate([[0.0], acum]))
        p = ini.loc[canal, "pct_con_ingreso"]
        primero = ini.loc[canal, "ingreso_primer_dia"]
        vp = p * (primero + descontar(inc * g[canal], tasa))
        sin_desc = p * (primero + np.cumsum(inc * g[canal]))
        filas.append(pd.DataFrame({"canal": canal, "mes": np.arange(1, meses + 1), "compras_acum": acum,
                                   "ltv": vp, "ltv_sin_descuento": sin_desc}))
    return pd.concat(filas, ignore_index=True)


def cac_reciente(tam: pd.DataFrame, meses: int = 6) -> pd.DataFrame:
    """CAC por canal en las últimas `meses` cohortes (gasto total / activaciones)."""
    ult = sorted(tam.cohorte.unique())[-meses:]
    t = tam[tam.cohorte.isin(ult)].groupby("canal")[["gasto", "clientes"]].sum()
    t["cac"] = t.gasto / t.clientes
    tot = tam.groupby("canal")[["gasto", "clientes"]].sum()
    t["cac_historico"] = tot.gasto / tot.clientes
    t["participacion_gasto"] = t.gasto / t.gasto.sum()
    return t.reset_index()


def resumen_canales(curvas: pd.DataFrame, cac: pd.DataFrame, emp: pd.DataFrame) -> pd.DataFrame:
    filas = []
    c = cac.set_index("canal")
    e = emp.set_index("canal")
    for canal, d in curvas.groupby("canal"):
        s = d.set_index("mes").ltv
        cac_c = float(c.loc[canal, "cac"]) if canal in c.index else 0.0
        filas.append({
            "canal": canal, "cac": cac_c,
            "ltv_12": s.loc[12], "ltv_24": s.loc[24],
            "ltv_12_sin_descuento": d.set_index("mes").ltv_sin_descuento.loc[12],
            "ltv_real_12": e.loc[canal, "ltv_real"] if canal in e.index else np.nan,
            "ltv_cac_12": s.loc[12] / cac_c if cac_c else np.nan,
            "ltv_cac_24": s.loc[24] / cac_c if cac_c else np.nan,
            "payback_meses": mes_payback(s, cac_c) if cac_c else np.nan,
            "participacion_gasto": float(c.loc[canal, "participacion_gasto"]) if canal in c.index else 0.0,
            "activaciones_6m": int(c.loc[canal, "clientes"]) if canal in c.index else 0,
        })
    return pd.DataFrame(filas).sort_values("ltv_cac_24", ascending=False, na_position="last")


def base_actual(compras: ModeloCompras, gasto: ModeloGasto, r: pd.DataFrame,
                tasa: float = TASA_MENSUAL) -> pd.DataFrame:
    """P(vivo), compras y valor esperado a 12 meses (descontado) de cada cliente al cierre."""
    acum = [np.zeros(len(r))]
    for m in range(1, 13):
        acum.append(compras.compras_esperadas(r, round(DIAS_MES * m)))
    inc = np.diff(np.vstack(acum), axis=0)
    desc = 1 / (1 + tasa) ** np.arange(1, 13)
    out = r[["customer_id", "canal", "region", "cohorte", "frequency", "recency", "T",
             "monetary_value", "ingreso_historico"]].copy()
    out["p_vivo"] = compras.prob_vivo(r)
    out["compras_12m"] = acum[-1]
    out["gasto_por_compra"] = gasto.gasto_esperado(r)
    out["valor_12m"] = (inc * desc[:, None]).sum(axis=0) * out.gasto_por_compra
    out["dias_sin_compra"] = out["T"] - out.recency
    out["segmento"] = segmentar(out)
    return out


def segmentar(df: pd.DataFrame) -> np.ndarray:
    """
    Segmentos para CRM. Valioso es el 20% que más ingreso dejó. "Valiosos en
    riesgo" son los que el modelo ya no da por seguros (P(vivo) bajo 0.9) pero
    tampoco por perdidos: es la lista que conviene llamar o premiar primero.
    """
    valioso = df.ingreso_historico >= df.ingreso_historico.quantile(0.80)
    p = df.p_vivo
    return np.select(
        [valioso & (p >= 0.9), valioso & (p >= 0.05), p >= 0.9, p >= 0.05],
        SEGMENTOS[:4], SEGMENTOS[4])


def calcular(con, seed: int = 7) -> dict[str, pd.DataFrame]:
    fin = q.fin_observacion(con)
    r = R.rfm(con, fin)
    canales = sorted(r.canal.unique())
    compras = ModeloCompras(canales, modificado=True).ajustar(r, seed=seed)
    gasto = ModeloGasto().ajustar(r, seed=seed)

    tam = q.tamanio_cohortes(con, ultima_cohorte=(pd.Timestamp(fin) - pd.offsets.MonthBegin(2)).date())
    matriz = q.matriz_cohortes(con)
    # p_ingreso con cohortes que ya tuvieron 30 días completos
    inicio = q.ingreso_primer_dia(con, hasta=(pd.Timestamp(fin) - pd.Timedelta(days=31)).date())
    curvas = curvas_nuevo_cliente(compras, gasto, inicio)
    cac = cac_reciente(tam)
    emp = q.ltv_empirico(matriz, 12)
    canales_res = resumen_canales(curvas, cac, emp)
    base = base_actual(compras, gasto, r)

    seg = (base.groupby("segmento").agg(clientes=("customer_id", "size"), p_vivo=("p_vivo", "mean"),
                                        ingreso_historico=("ingreso_historico", "sum"),
                                        valor_12m=("valor_12m", "sum")).reset_index())
    return {"ltv_curvas": curvas, "ltv_canales": canales_res, "cac": cac, "ingreso_inicio": inicio,
            "base_actual": base, "segmentos": seg, "parametros_bgnbd": compras.parametros(),
            "gasto_nuevo": pd.DataFrame([{"canal": k, "gasto_por_compra": v} for k, v in gasto.gasto_nuevo().items()]),
            "cierre": pd.DataFrame([{"fin_observacion": fin, "clientes_modelo": len(r),
                                     "tasa_mensual": TASA_MENSUAL}])}


def cohortes(con) -> dict[str, pd.DataFrame]:
    """Tablas de cohortes (todo SQL) para el tablero."""
    fin = q.fin_observacion(con)
    tam = q.tamanio_cohortes(con, ultima_cohorte=(pd.Timestamp(fin) - pd.offsets.MonthBegin(2)).date())
    matriz = q.matriz_cohortes(con)
    total = q.matriz_cohortes(con, por_canal=False)
    return {"tam_cohortes": tam, "matriz": matriz, "matriz_total": total,
            "retencion_canal": q.retencion_promedio(matriz),
            "payback_cohortes": q.payback_empirico(matriz, tam),
            "ltv_real_12": q.ltv_empirico(matriz, 12), "mezcla_ingreso": q.mezcla_ingreso(con)}
