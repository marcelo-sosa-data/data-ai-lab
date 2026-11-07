"""
Tablero de cohortes y valor de vida: retorno por canal, triángulo de cohortes,
validación del modelo y segmentos de la base actual.

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from cohortes.ltv import SEGMENTOS  # noqa: E402
from cohortes.resultados import tablas  # noqa: E402
from cohortes.rutas import ruta_db, ruta_resultados  # noqa: E402

st.set_page_config(page_title="cohortes · Ayni", page_icon=":material/stacked_line_chart:", layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.45rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
[data-testid="stMetricDelta"] { font-family: 'JetBrains Mono', monospace; font-size: .8rem; }
[data-testid="stMetric"] { border: 1px solid #1F2A36; border-radius: 8px; padding: 12px 16px; background: #0F151C; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.estado { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #7D8B99;
          border: 1px solid #1F2A36; border-radius: 6px; padding: 6px 10px; display: inline-block; }
.estado b { color: #34D399; font-weight: 600; }
.nota { font-size: .85rem; color: #9AA7B4; }
.nota b { color: #D6DEE6; font-family: 'JetBrains Mono', monospace; font-weight: 600; }
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO = "#22D3EE"
GRIS = "#7D8B99"
GRIS_OSCURO = "#46535F"
AMBAR = "#FBBF24"
ROJO = "#F87171"
VERDE = "#34D399"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
ORDEN_CANALES = ["Referidos", "Google Search", "Orgánico", "Agentes en tienda", "Meta Ads", "TikTok Ads", "Influencers"]
COLORES_CANALES = [ACENTO, "#A78BFA", "#9AA7B4", VERDE, AMBAR, ROJO, "#F472B6"]


@alt.theme.register("consola", enable=True)
def tema_oscuro():
    return alt.theme.ThemeConfig({"config": {
        "background": "transparent",
        "view": {"stroke": "transparent"},
        "font": "Inter",
        "axis": {"labelColor": "#9AA7B4", "titleColor": "#7D8B99", "gridColor": "#1A222C",
                 "domainColor": "#2A3542", "tickColor": "#2A3542", "labelFontSize": 11,
                 "titleFontSize": 11, "titleFontWeight": 500},
        "legend": {"labelColor": "#9AA7B4", "titleColor": "#7D8B99", "labelFontSize": 11, "titleFontSize": 11},
    }})


def mes_corto(f) -> str:
    f = pd.Timestamp(f)
    return f"{MESES[f.month - 1]} {str(f.year)[2:]}"


def dia_corto(f) -> str:
    f = pd.Timestamp(f)
    return f"{f.day:02d} {MESES[f.month - 1]}"


DB, RES = ruta_db(), ruta_resultados()
NECESARIAS = {"matriz", "ltv_canales", "val_general", "base_actual"}
if not DB.exists() or not NECESARIAS <= tablas(RES):
    st.error("Faltan los datos o los resultados.", icon=":material/database:")
    st.code("python -m cohortes todo", language="bash")
    st.stop()


@st.cache_data(show_spinner=False)
def tabla(nombre: str) -> pd.DataFrame:
    con = duckdb.connect(str(RES), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {nombre}").df()
    finally:
        con.close()


CIERRE = tabla("cierre").iloc[0]
LTV = tabla("ltv_canales")
CURVAS = tabla("ltv_curvas")
MATRIZ = tabla("matriz")
TAM = tabla("tam_cohortes")
VAL = tabla("val_resumen").iloc[0]

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Ayni, billetera digital")
    st.caption(f"Tarjeta prepago y billetera · cohortes ene 25 – {mes_corto(TAM.cohorte.max())} · "
               f"datos al {pd.Timestamp(CIERRE.fin_observacion):%d/%m/%Y} · empresa y datos ficticios")
    canales_sel = st.multiselect("Canales", ORDEN_CANALES, default=ORDEN_CANALES)
    st.subheader("Supuestos")
    st.markdown(
        f'<div class="nota">Una compra es un día con ingreso neto<br>'
        f'Costo de capital <b>{CIERRE.tasa_mensual:.0%}</b> mensual<br>'
        f'CAC de las últimas <b>6</b> cohortes<br>'
        f'Modelo: <b>MBG/NBD</b> con canal + <b>Gamma-Gamma</b> por canal<br>'
        f'<b>{CIERRE.clientes_modelo:,}</b> clientes en el ajuste</div>', unsafe_allow_html=True)

canales_sel = canales_sel or ORDEN_CANALES
color_canal = alt.Color("canal:N", title=None, sort=ORDEN_CANALES,
                        scale=alt.Scale(domain=ORDEN_CANALES, range=COLORES_CANALES),
                        legend=alt.Legend(orient="top", columns=4))

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> cohortes</p>', unsafe_allow_html=True)
st.caption("Cuánto deja cada cuenta activada según el canal que la trajo, cuánto costó traerla y en qué mes "
           "se recupera. Las cohortes salen de SQL; el valor futuro, de un MBG/NBD y un Gamma-Gamma.")
st.markdown(f'<div class="estado"><b>●</b> duckdb · {DB.name} · {MATRIZ.cohorte.nunique()} cohortes · '
            f'holdout {pd.Timestamp(VAL.corte):%d/%m/%Y} → {pd.Timestamp(VAL.fin):%d/%m/%Y}</div>',
            unsafe_allow_html=True)
st.write("")

tab_canal, tab_coh, tab_val, tab_base = st.tabs([
    ":material/payments: Retorno por canal", ":material/grid_on: Cohortes",
    ":material/fact_check: Validación", ":material/group: Base actual"])

# ----------------------------------------------------------------- retorno por canal

with tab_canal:
    pagados = LTV[LTV.cac > 0]
    gasto_6m = TAM[TAM.cohorte.isin(sorted(TAM.cohorte.unique())[-6:])].gasto.sum()
    no_recupera = pagados[pagados.ltv_cac_24 < 1].participacion_gasto.sum()
    ponderado = (pagados.ltv_24 * pagados.activaciones_6m).sum() / (pagados.cac * pagados.activaciones_6m).sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gasto últimos 6 meses", f"S/ {gasto_6m / 1e3:,.0f} mil")
    c2.metric("LTV/CAC 24m ponderado", f"{ponderado:.2f}")
    c3.metric("Gasto en canales con LTV/CAC < 1", f"{no_recupera:.0%}")
    mejor = pagados.sort_values("ltv_cac_24").iloc[-1]
    c4.metric("Mejor canal pagado", mejor.canal, f"payback mes {mejor.payback_meses:.0f}", delta_color="off",
              delta_arrow="off")

    izq, der = st.columns([1.05, 1])
    with izq:
        st.markdown("#### LTV a 24 meses contra CAC")
        d = LTV[LTV.canal.isin(canales_sel)].copy()
        largo = pd.concat([d.assign(medida="LTV 24m", valor=d.ltv_24),
                           d[d.cac > 0].assign(medida="CAC", valor=d.cac)])
        barras = alt.Chart(largo).mark_bar(cornerRadiusEnd=2, height=11).encode(
            y=alt.Y("canal:N", sort=ORDEN_CANALES, title=None, axis=alt.Axis(labelLimit=180, minExtent=118)),
            yOffset=alt.YOffset("medida:N", sort=["LTV 24m", "CAC"]),
            x=alt.X("valor:Q", title="S/ por cuenta activada"),
            color=alt.Color("medida:N", title=None, scale=alt.Scale(domain=["LTV 24m", "CAC"],
                                                                     range=[ACENTO, GRIS_OSCURO]),
                            legend=alt.Legend(orient="top")),
            tooltip=["canal", "medida", alt.Tooltip("valor:Q", format=",.2f", title="S/")])
        st.altair_chart(barras.properties(height=340), width="stretch")
    with der:
        st.markdown("#### LTV acumulado por mes de vida")
        canal_curva = st.selectbox("Canal", [c for c in ORDEN_CANALES if c in canales_sel and c != "Orgánico"],
                                   label_visibility="collapsed")
        cv = CURVAS[CURVAS.canal == canal_curva]
        cac_c = float(LTV.set_index("canal").loc[canal_curva, "cac"])
        real = MATRIZ[(MATRIZ.canal == canal_curva)]
        real = (real.assign(mes=real.k + 1, ing=real.ingreso_acum_cliente * real.clientes)
                .groupby("mes").agg(ing=("ing", "sum"), clientes=("clientes", "sum"),
                                    cohortes=("cohorte", "nunique")).reset_index())
        real = real[(real.cohortes >= 6) & (real.mes <= 24)].assign(valor=lambda x: x.ing / x.clientes)
        base = alt.Chart(cv).encode(x=alt.X("mes:Q", title="Mes de vida", scale=alt.Scale(domain=[1, 24]),
                                            axis=alt.Axis(values=list(range(0, 25, 3)))))
        linea = base.mark_line(color=ACENTO, strokeWidth=2.5).encode(
            y=alt.Y("ltv:Q", title="S/ acumulados por cuenta"),
            tooltip=["mes", alt.Tooltip("ltv:Q", format=",.2f", title="LTV (VP)")])
        puntos = alt.Chart(real).mark_circle(color=AMBAR, size=34).encode(
            x="mes:Q", y="valor:Q",
            tooltip=["mes", alt.Tooltip("valor:Q", format=",.2f", title="Real (sin descontar)"), "cohortes"])
        regla = alt.Chart(pd.DataFrame({"cac": [cac_c]})).mark_rule(color=ROJO, strokeDash=[4, 3]).encode(y="cac:Q")
        st.altair_chart((linea + puntos + regla).properties(height=300), width="stretch")
        st.caption(f"Línea: modelo, a valor presente. Puntos: lo observado en cohortes con al menos 6 meses de "
                   f"historia. Rojo: CAC de S/ {cac_c:,.2f}.")

    vista = LTV[LTV.canal.isin(canales_sel)][["canal", "cac", "ltv_12_sin_descuento", "ltv_real_12", "ltv_24",
                                              "ltv_cac_24", "payback_meses", "participacion_gasto"]].copy()
    vista["cac"] = vista.cac.where(vista.cac > 0)
    vista["payback"] = [("-" if pd.isna(c) else ("más de 24 meses" if pd.isna(p) else f"mes {p:.0f}"))
                        for c, p in zip(vista.cac, vista.payback_meses)]
    st.dataframe(
        vista.drop(columns="payback_meses"), hide_index=True, width="stretch",
        column_config={
            "canal": "Canal", "cac": st.column_config.NumberColumn("CAC", format="S/ %.2f"),
            "ltv_12_sin_descuento": st.column_config.NumberColumn("Modelo 12m", format="S/ %.2f"),
            "ltv_real_12": st.column_config.NumberColumn("Real 12m", format="S/ %.2f"),
            "ltv_24": st.column_config.NumberColumn("LTV 24m (VP)", format="S/ %.2f"),
            "ltv_cac_24": st.column_config.NumberColumn("LTV/CAC", format="%.2f"),
            "participacion_gasto": st.column_config.ProgressColumn("% del gasto", format="percent",
                                                                   min_value=0, max_value=1),
            "payback": "Payback"})

# ----------------------------------------------------------------- cohortes

with tab_coh:
    a, b = st.columns([1, 2])
    canal_coh = a.selectbox("Canal de la cohorte", ["Todos"] + [c for c in ORDEN_CANALES if c in canales_sel])
    medida = b.radio("Medida", ["Retención", "Ingreso acumulado por cuenta", "Ingreso acumulado / CAC"],
                     horizontal=True)
    if canal_coh == "Todos":
        m = tabla("matriz_total")
        tam = TAM.groupby("cohorte")[["gasto", "clientes"]].sum().reset_index()
        pag = TAM[TAM.canal != "Orgánico"].groupby("cohorte")[["gasto", "clientes"]].sum()
        tam["cac"] = tam.cohorte.map(pag.gasto / pag.clientes)
    else:
        m = MATRIZ[MATRIZ.canal == canal_coh]
        tam = TAM[TAM.canal == canal_coh]
    m = m.merge(tam[["cohorte", "cac"]], on="cohorte", how="left")
    m = m[m.k <= 18].copy()
    m["etiqueta"] = [mes_corto(c) for c in m.cohorte]
    orden = [mes_corto(c) for c in sorted(m.cohorte.unique())]
    if medida == "Retención":
        m["valor"], fmt, esquema = m.retencion, ".0%", "tealblues"
    elif medida == "Ingreso acumulado por cuenta":
        m["valor"], fmt, esquema = m.ingreso_acum_cliente, ",.2f", "tealblues"
    else:
        m = m[m.cac > 0]
        m["valor"], fmt, esquema = m.ingreso_acum_cliente / m.cac, ".2f", "redyellowblue"
    escala = (alt.Scale(scheme=esquema, domainMid=1, domain=[0, 2], clamp=True) if medida.endswith("CAC")
              else alt.Scale(scheme=esquema))
    calor = alt.Chart(m).mark_rect(stroke="#0B0F14", strokeWidth=1).encode(
        x=alt.X("k:O", title="Mes de vida", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("etiqueta:O", sort=orden, title=None),
        color=alt.Color("valor:Q", scale=escala, title=None, legend=alt.Legend(format=fmt)),
        tooltip=[alt.Tooltip("etiqueta:N", title="Cohorte"), alt.Tooltip("k:O", title="Mes"),
                 alt.Tooltip("clientes:Q", format=",", title="Cuentas"),
                 alt.Tooltip("valor:Q", format=fmt, title=medida)])
    texto = calor.mark_text(fontSize=9, font="JetBrains Mono").encode(
        text=alt.Text("valor:Q", format=fmt if fmt != ",.2f" else ",.0f"),
        color=alt.value("#0B0F14"))
    st.altair_chart((calor + texto).properties(height=560), width="stretch")
    if medida.endswith("CAC"):
        st.caption("Sobre 1 la cohorte ya recuperó lo que costó traerla. Orgánico no entra porque no tiene gasto.")
    st.caption("Las cohortes de nov 25 y abr 26 son las de la campaña de S/ 20 de bono en TikTok e influencers.")

    st.markdown("#### Retención por canal")
    r = tabla("retencion_canal")
    r = r[(r.canal.isin(canales_sel)) & (r.k >= 1) & (r.k <= 18)]
    lineas = alt.Chart(r).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=18)).encode(
        x=alt.X("k:Q", title="Mes de vida", axis=alt.Axis(values=list(range(1, 19)))),
        y=alt.Y("retencion:Q", title="Cuentas con transacción en el mes", axis=alt.Axis(format="%")),
        color=color_canal,
        tooltip=["canal", "k", alt.Tooltip("retencion:Q", format=".1%"), "cohortes"])
    st.altair_chart(lineas.properties(height=320), width="stretch")

# ----------------------------------------------------------------- validación

with tab_val:
    g = tabla("val_general")
    st.markdown(f'<div class="nota">Ajuste con lo conocido hasta el <b>{pd.Timestamp(VAL.corte):%d/%m/%Y}</b> '
                f'(<b>{VAL.clientes:,.0f}</b> clientes) y predicción de sus compras en los <b>{VAL.dias:.0f}</b> '
                f'días siguientes.</div>', unsafe_allow_html=True)
    st.write("")
    cols = st.columns(len(g))
    for col, f in zip(cols, g.itertuples()):
        col.metric(f.modelo, f"{f.error_total_pct:+.1%}", f"MAE {f.mae_cliente:.2f}", delta_color="off",
                   delta_arrow="off")

    s = tabla("val_semanal")
    s["etiqueta"] = [dia_corto(f) for f in s.inicio]
    largo = pd.concat([s.assign(serie="Predicho (MBG/NBD)", valor=s.compras_pred),
                       s.assign(serie="Real", valor=s.compras_real)])
    st.caption("Error total: compras predichas sobre reales en el holdout. MAE: error absoluto medio por cliente.")
    st.markdown("#### Compras por semana en el holdout")
    serie = alt.Chart(largo).mark_line(strokeWidth=2.2, point=alt.OverlayMarkDef(size=22)).encode(
        x=alt.X("etiqueta:O", sort=list(s.etiqueta), title=None, axis=alt.Axis(labelAngle=-45)),
        # serie de tiempo: el eje no arranca en cero
        y=alt.Y("valor:Q", title="Días con ingreso", scale=alt.Scale(zero=False, nice=True)),
        color=alt.Color("serie:N", title=None, scale=alt.Scale(domain=["Predicho (MBG/NBD)", "Real"],
                                                               range=[ACENTO, AMBAR]),
                        legend=alt.Legend(orient="top")),
        tooltip=["etiqueta", "serie", alt.Tooltip("valor:Q", format=",.0f")])
    st.altair_chart(serie.properties(height=300), width="stretch")
    st.caption("El modelo no sabe de estacionalidad: en julio, con la gratificación, la gente usa más la tarjeta.")

    izq, der = st.columns(2)
    with izq:
        st.markdown("#### Error total por canal")
        vc = tabla("val_canal")
        largo = pd.concat([vc.assign(modelo=n, error=vc[f"error_{k}"]) for k, n in
                           [("bgnbd", "BG/NBD sin canal"), ("bgnbd_canal", "BG/NBD con canal"),
                            ("mbgnbd_canal", "MBG/NBD con canal")]])
        err = alt.Chart(largo[largo.canal.isin(canales_sel)]).mark_bar(height=8, cornerRadiusEnd=2).encode(
            y=alt.Y("canal:N", sort=ORDEN_CANALES, title=None, axis=alt.Axis(labelLimit=180, minExtent=118)),
            yOffset=alt.YOffset("modelo:N"),
            x=alt.X("error:Q", title="Predicho / real - 1", axis=alt.Axis(format="%")),
            color=alt.Color("modelo:N", title=None, scale=alt.Scale(
                domain=["BG/NBD sin canal", "BG/NBD con canal", "MBG/NBD con canal"],
                range=[GRIS_OSCURO, GRIS, ACENTO]), legend=alt.Legend(orient="top", columns=2)),
            tooltip=["canal", "modelo", alt.Tooltip("error:Q", format="+.1%")])
        st.altair_chart(err.properties(height=320), width="stretch")
    with der:
        st.markdown("#### P(vivo) contra lo que pasó")
        pv = tabla("val_p_vivo")
        diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(
            color=GRIS_OSCURO, strokeDash=[4, 3]).encode(x="x:Q", y="y:Q")
        pts = alt.Chart(pv).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("p_vivo:Q", title="P(vivo) promedio del decil", axis=alt.Axis(format="%")),
            y=alt.Y("vivo_real:Q", title="Seguían activos de verdad", axis=alt.Axis(format="%")),
            color=alt.Color("modelo:N", title=None, scale=alt.Scale(
                domain=["BG/NBD con canal", "MBG/NBD con canal"], range=[ROJO, ACENTO]),
                legend=alt.Legend(orient="top")),
            tooltip=["modelo", "decil", alt.Tooltip("p_vivo:Q", format=".1%"),
                     alt.Tooltip("vivo_real:Q", format=".1%")])
        st.altair_chart((diag + pts).properties(height=320), width="stretch")
        st.caption(f"Con una sola compra seguían activos el {VAL.una_compra_vivos:.0%}. El BG/NBD les da "
                   f"{VAL.una_compra_p_bg:.0%} de P(vivo) y el MBG/NBD {VAL.una_compra_p_mbg:.0%}. "
                   f"Brier: {VAL.brier_bg:.3f} contra {VAL.brier_mbg:.3f}.")

# ----------------------------------------------------------------- base actual

with tab_base:
    seg = tabla("segmentos").set_index("segmento")
    cols = st.columns(len(SEGMENTOS))
    for col, nombre in zip(cols, SEGMENTOS):
        if nombre in seg.index:
            f = seg.loc[nombre]
            col.metric(nombre, f"{f.clientes:,.0f}", f"S/ {f.valor_12m / 1e3:,.1f} mil", delta_color="off",
                       delta_arrow="off", help="Clientes y valor esperado a 12 meses (valor presente)")

    base = tabla("base_actual")
    base = base[base.canal.isin(canales_sel)]
    st.markdown("#### Valiosos en riesgo")
    st.caption("El 20% que más ingreso dejó y que el modelo ya no da por seguro. Ordenados por lo que se pierde "
               "si se van: ingreso histórico por (1 - P(vivo)).")
    riesgo = base[base.segmento == "Valiosos en riesgo"].copy()
    riesgo["en_juego"] = riesgo.ingreso_historico * (1 - riesgo.p_vivo)
    riesgo = riesgo.sort_values("en_juego", ascending=False)
    riesgo["cohorte"] = [mes_corto(c) for c in riesgo.cohorte]
    cols_vista = ["customer_id", "canal", "region", "cohorte", "frequency", "dias_sin_compra",
                  "ingreso_historico", "p_vivo", "valor_12m"]
    st.dataframe(riesgo[cols_vista], hide_index=True, width="stretch", height=360, column_config={
        "customer_id": st.column_config.NumberColumn("Cliente", format="%d"), "canal": "Canal",
        "region": "Región", "cohorte": "Cohorte",
        "frequency": st.column_config.NumberColumn("Compras repetidas", format="%d"),
        "dias_sin_compra": st.column_config.NumberColumn("Días sin compra", format="%d"),
        "ingreso_historico": st.column_config.NumberColumn("Ingreso histórico", format="S/ %.2f"),
        "p_vivo": st.column_config.ProgressColumn("P(vivo)", format="percent", min_value=0, max_value=1),
        "valor_12m": st.column_config.NumberColumn("Valor esperado 12m", format="S/ %.2f")})
    st.download_button("Descargar lista (CSV)", riesgo[cols_vista].to_csv(index=False).encode("utf-8"),
                       "valiosos_en_riesgo.csv", "text/csv", icon=":material/download:")

    st.markdown("#### Valor esperado a 12 meses por canal y segmento")
    vs = base.groupby(["canal", "segmento"]).valor_12m.sum().reset_index()
    apil = alt.Chart(vs).mark_bar(cornerRadiusEnd=2).encode(
        y=alt.Y("canal:N", sort=ORDEN_CANALES, title=None, axis=alt.Axis(labelLimit=180, minExtent=118)),
        x=alt.X("valor_12m:Q", title="S/ esperados (valor presente)"),
        color=alt.Color("segmento:N", sort=SEGMENTOS, title=None, scale=alt.Scale(
            domain=SEGMENTOS, range=[ACENTO, AMBAR, "#0E7490", GRIS, GRIS_OSCURO]),
            legend=alt.Legend(orient="top", columns=3)),
        tooltip=["canal", "segmento", alt.Tooltip("valor_12m:Q", format=",.0f", title="S/")])
    st.altair_chart(apil.properties(height=300), width="stretch")
