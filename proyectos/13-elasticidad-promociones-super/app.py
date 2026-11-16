"""
Tablero de promociones de Qollqa: simulador de margen antes de aprobar una oferta,
evaluación del calendario de may-oct 2026, elasticidades y ventas semanales.

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from elasticidad import modelo as M  # noqa: E402
from elasticidad.consultas import conectar, matrices  # noqa: E402
from elasticidad.evaluacion import PROB_APROBAR  # noqa: E402
from elasticidad.resultados import leer, tablas  # noqa: E402
from elasticidad.rutas import ruta_db, ruta_modelos, ruta_resultados  # noqa: E402
from elasticidad.simulador import DESCUENTOS, Escenario, Simulador  # noqa: E402

st.set_page_config(page_title="promociones · Qollqa", page_icon=":material/sell:", layout="wide")

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
.veredicto { border: 1px solid #1F2A36; border-left: 3px solid var(--c); border-radius: 6px;
             padding: 10px 14px; background: #0F151C; font-size: .92rem; }
.veredicto b { font-family: 'JetBrains Mono', monospace; }
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


def dia_mes(f) -> str:
    f = pd.Timestamp(f)
    return f"{f.day:02d} {MESES[f.month - 1]} {str(f.year)[2:]}"


def soles(x: float) -> str:
    signo = "-" if x < 0 else ""
    return f"{signo}S/ {abs(x):,.0f}"


DB, RES, MOD = ruta_db(), ruta_resultados(), ruta_modelos()
NECESARIAS = {"elasticidades", "eval_promos", "eval_resumen"}
if not DB.exists() or not (MOD / "final.npz").exists() or not NECESARIAS <= tablas(RES):
    st.error("Faltan los datos, el modelo o los resultados.", icon=":material/database:")
    st.code("python -m elasticidad todo", language="bash")
    st.stop()


@st.cache_resource(show_spinner=False)
def cargar():
    con = conectar(DB)
    m = matrices(con)
    post, meta, diag = M.cargar(MOD, "final")
    promos = con.execute("SELECT pr.*, p.descripcion FROM promociones pr JOIN productos p USING (id_sku)").df()
    con.close()
    return m, Simulador(post, meta, m, semanas_futuras=16, n_draws=400), diag, promos


@st.cache_data(show_spinner=False)
def tabla(nombre: str) -> pd.DataFrame:
    return leer(RES, nombre)


m, sim, DIAG, PROMOS = cargar()
SKUS = m.skus.set_index("id_sku")
ELAS = tabla("elasticidades")
EV = tabla("eval_promos")
RESUMEN = tabla("eval_resumen").set_index("indicador")

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Supermercados Qollqa")
    st.caption(f"{int(m.locales.sum())} locales en Lima y Callao · {len(SKUS)} productos de "
               f"{len(m.categorias)} categorías · semanas del {dia_mes(m.semanas[0])} al "
               f"{dia_mes(m.semanas[-1])} · empresa y datos ficticios")
    st.subheader("Modelo")
    st.markdown(
        f'<div class="nota">Binomial negativa jerárquica en <b>PyMC</b><br>'
        f'NUTS con nutpie: <b>{DIAG["draws"]:,}</b> draws<br>'
        f'r_hat máx <b>{DIAG["rhat_max"]:.3f}</b> · ESS mín <b>{DIAG["ess_min"]:.0f}</b><br>'
        f'Divergencias: <b>{DIAG["divergencias"]}</b><br>'
        f'Ventana de medición: promoción + <b>2</b> semanas<br>'
        f'Se aprueba con P(gana margen) ≥ <b>{PROB_APROBAR:.0%}</b></div>', unsafe_allow_html=True)

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> promociones</p>', unsafe_allow_html=True)
st.caption("Cuánto margen deja una oferta en toda la categoría, contando lo que les quita a las otras marcas y lo "
           "que se deja de vender después. Las elasticidades salen de un modelo bayesiano jerárquico.")
st.markdown(f'<div class="estado"><b>●</b> duckdb · {DB.name} · {len(PROMOS)} promociones en el histórico · '
            f'evaluación con corte al {dia_mes(EV.inicio.min())}</div>', unsafe_allow_html=True)
st.write("")

tab_sim, tab_eval, tab_elas, tab_ventas = st.tabs([
    ":material/tune: Simulador", ":material/fact_check: Calendario may-oct",
    ":material/insights: Elasticidades", ":material/show_chart: Ventas semanales"])

# ----------------------------------------------------------------- simulador

with tab_sim:
    c1, c2, c3 = st.columns([1.1, 1.1, 1])
    with c1:
        cat = st.selectbox("Categoría", m.categorias, index=m.categorias.index("Gaseosas"))
        opciones = SKUS[SKUS.categoria == cat]
        sku = st.selectbox("Producto", opciones.index, format_func=lambda s: f"{s} · {SKUS.loc[s, 'descripcion']}")
    with c2:
        futuras = [s for s in sim.semanas if s > sim.ultima_observada][:12]
        inicio = st.selectbox("Semana de inicio", futuras, format_func=lambda s: f"lunes {dia_mes(s)}")
        semanas = st.radio("Duración", [1, 2], format_func=lambda n: f"{n} semana" + ("s" if n > 1 else ""),
                           horizontal=True)
    with c3:
        descuento = st.slider("Descuento", 5, 40, 20, step=5, format="%d%%") / 100
        aporte = st.slider("Aporte del proveedor (parte del descuento)", 0, 100, 60, step=10, format="%d%%") / 100
        encarte = st.toggle("Sale en el encarte", value=True)

    esc = Escenario(sku, pd.Timestamp(inicio), semanas, descuento, encarte, aporte)
    draws = sim.simular(esc)
    r = sim.resumir(esc)
    rec = sim.recomendar(esc)
    i = list(m.skus.id_sku).index(sku)
    t0 = sim._semana(inicio)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Margen incremental", soles(r["margen_media"]),
              help="Toda la categoría, durante la promoción y las dos semanas siguientes.")
    k2.metric("P(gana margen)", f"{r['prob_gana']:.0%}")
    k3.metric("Venta incremental", soles(r["venta_media"]))
    k4.metric("Precio de oferta", f"S/ {sim.regular[t0, i] * (1 - descuento):.2f}",
              help=f"Precio regular: S/ {sim.regular[t0, i]:.2f}")

    if r["prob_gana"] >= PROB_APROBAR:
        color, texto = VERDE, f"Se aprueba: gana margen con probabilidad <b>{r['prob_gana']:.0%}</b>."
    else:
        color, texto = ROJO, f"No se aprueba así: gana margen solo con probabilidad <b>{r['prob_gana']:.0%}</b>."
    if rec["descuento"] == 0:
        texto += " Con estas condiciones ningún descuento de la grilla gana margen con seguridad suficiente."
    elif not np.isclose(rec["descuento"], descuento):
        texto += (f" El mejor descuento con estas condiciones es <b>{rec['descuento']:.0%}</b>, con "
                  f"<b>{soles(rec['margen_media'])}</b> esperados.")
    st.markdown(f'<div class="veredicto" style="--c:{color}">{texto}</div>', unsafe_allow_html=True)
    st.write("")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### De dónde salen las unidades")
        partes = pd.DataFrame({
            "concepto": ["Extra del producto", "Otras marcas", "Semanas siguientes"],
            "unidades": [r["unid_propias"], r["unid_canibalizadas"], r["unid_post"]],
        })
        partes["color"] = [ACENTO, ROJO, AMBAR]
        barras = alt.Chart(partes).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("concepto:N", title=None, sort=None),
            x=alt.X("unidades:Q", title="unidades"),
            color=alt.Color("color:N", scale=None),
            tooltip=["concepto", alt.Tooltip("unidades:Q", format=",.0f")])
        st.altair_chart(barras.properties(height=180), width="stretch")
        neto = r["unid_propias"] + r["unid_canibalizadas"] + r["unid_post"]
        st.caption(f"De cada 100 unidades extra del producto, la categoría se queda con "
                   f"{100 * neto / max(r['unid_propias'], 1):.0f}.")
    with g2:
        st.markdown("#### Margen incremental según el descuento")
        curva = rec["curva"].copy()
        curva["etiqueta"] = [f"{d:.0%}" for d in curva.descuento]
        base = alt.Chart(curva).encode(x=alt.X("etiqueta:O", title="descuento", sort=None,
                                               axis=alt.Axis(labelAngle=0)))
        banda = base.mark_area(color=ACENTO, opacity=0.15).encode(
            y=alt.Y("margen_p05:Q", title="S/"), y2="margen_p95:Q")
        linea = base.mark_line(color=ACENTO, strokeWidth=2.5).encode(y="margen_media:Q")
        puntos = base.mark_circle(size=60).encode(
            y="margen_media:Q",
            color=alt.condition(alt.datum.prob_gana >= PROB_APROBAR, alt.value(VERDE), alt.value(GRIS)),
            tooltip=["etiqueta", alt.Tooltip("margen_media:Q", title="margen", format=",.0f"),
                     alt.Tooltip("prob_gana:Q", title="P(gana)", format=".0%")])
        cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=GRIS_OSCURO, strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart((banda + linea + puntos + cero).properties(height=220), width="stretch")
        st.caption("Banda: intervalo de 90% de la posterior. En verde, los descuentos que se aprobarían.")

# ----------------------------------------------------------------- evaluación

with tab_eval:
    st.caption(f"El modelo se ajustó con las semanas anteriores al {dia_mes(EV.inicio.min())} y estimó las "
               f"{len(EV)} promociones que se hicieron después. El margen real existe porque los datos son simulados.")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Margen real, todo", soles(RESUMEN.loc["margen incremental real de lo aprobado (S/)", "asis"]),
              help=f"Las {len(EV)} promociones que se ejecutaron.")
    k2.metric("Margen real, aprobadas", soles(RESUMEN.loc["margen incremental real de lo aprobado (S/)", "tobe"]),
              help=f"Las {int(RESUMEN.loc['promociones aprobadas', 'tobe'])} que el modelo aprobaría.")
    k3.metric("Con descuento sugerido",
              soles(RESUMEN.loc["margen incremental real con el descuento recomendado (S/)", "tobe"]),
              help="Cada promoción con el descuento que recomienda el modelo, o sin promoción.")
    k4.metric("Error medio", soles(RESUMEN.loc["error absoluto medio del margen incremental (S/)", "tobe"]),
              help="Error absoluto medio del margen estimado por promoción.")
    st.caption(f"El modelo aprueba {int(RESUMEN.loc['promociones aprobadas', 'tobe'])} de {len(EV)}. "
               f"La planilla se equivocaba en "
               f"{soles(RESUMEN.loc['error absoluto medio del margen incremental (S/)', 'asis'])} por promoción.")

    st.markdown("#### Margen estimado frente al real, por promoción")
    largo = pd.concat([
        EV.assign(metodo="Planilla (AS IS)", estimado=EV.asis_margen),
        EV.assign(metodo="Modelo (TO BE)", estimado=EV.tobe_margen),
    ])
    lim = [float(min(largo.estimado.min(), largo.real_margen.min())) * 1.05,
           float(max(largo.estimado.max(), largo.real_margen.max())) * 1.05]
    puntos = alt.Chart(largo).mark_circle(size=70, opacity=0.85).encode(
        x=alt.X("real_margen:Q", title="margen incremental real (S/)", scale=alt.Scale(domain=lim)),
        y=alt.Y("estimado:Q", title="estimado (S/)", scale=alt.Scale(domain=lim)),
        color=alt.Color("metodo:N", title=None, scale=alt.Scale(domain=["Planilla (AS IS)", "Modelo (TO BE)"],
                                                                range=[AMBAR, ACENTO]),
                        legend=alt.Legend(orient="top")),
        tooltip=["id_promo", "descripcion", alt.Tooltip("descuento:Q", format=".0%"),
                 alt.Tooltip("estimado:Q", format=",.0f"), alt.Tooltip("real_margen:Q", format=",.0f")])
    diag = alt.Chart(pd.DataFrame({"x": lim, "y": lim})).mark_line(color=GRIS_OSCURO, strokeDash=[4, 4]).encode(
        x="x:Q", y="y:Q")
    st.altair_chart((diag + puntos).properties(height=360), width="stretch")

    st.markdown("#### Detalle")
    vista = EV.round({"asis_margen": 0, "tobe_margen": 0, "real_margen": 0}).assign(
        inicio=EV.inicio.map(dia_mes),
        decision=np.where(EV.tobe_aprueba, "Aprobar", np.where(EV.rec_descuento > 0, "Cambiar descuento", "No hacer")),
    )[["id_promo", "inicio", "descripcion", "descuento", "aporte_pct", "asis_margen", "tobe_margen", "tobe_prob",
       "real_margen", "decision", "rec_descuento"]]
    st.dataframe(vista, hide_index=True, width="stretch", column_config={
        "id_promo": "Promoción", "inicio": "Inicio", "descripcion": "Producto",
        "descuento": st.column_config.NumberColumn("Descuento", format="percent"),
        "aporte_pct": st.column_config.NumberColumn("Aporte proveedor", format="percent"),
        "asis_margen": st.column_config.NumberColumn("Planilla S/", format="localized"),
        "tobe_margen": st.column_config.NumberColumn("Modelo S/", format="localized"),
        "tobe_prob": st.column_config.ProgressColumn("P(gana)", format="percent", min_value=0, max_value=1),
        "real_margen": st.column_config.NumberColumn("Real S/", format="localized"),
        "decision": "Decisión TO BE",
        "rec_descuento": st.column_config.NumberColumn("Descuento sugerido", format="percent"),
    })
    st.download_button("Descargar CSV", EV.to_csv(index=False).encode("utf-8"), "evaluacion_promociones.csv",
                       "text/csv")

# ----------------------------------------------------------------- elasticidades

with tab_elas:
    st.caption("Elasticidad al descuento de cada producto en el formato Super, con su intervalo de 90%. "
               "Hiper y Express escalan la sensibilidad con el multiplicador de su formato.")
    cats_sel = st.multiselect("Categorías", m.categorias, default=m.categorias)
    e = ELAS[ELAS.categoria.isin(cats_sel or m.categorias)].copy()
    e["producto"] = e.id_sku + " · " + e.descripcion
    orden = e.sort_values("elasticidad").producto.tolist()
    y = alt.Y("producto:N", title=None, sort=orden)
    rango = alt.Chart(e).mark_rule(color=GRIS, strokeWidth=2).encode(
        y=y, x=alt.X("p05:Q", title="elasticidad"), x2="p95:Q")
    punto = alt.Chart(e).mark_circle(size=70, color=ACENTO).encode(
        y=y, x="elasticidad:Q",
        tooltip=["descripcion", "categoria", alt.Tooltip("elasticidad:Q", format=".2f"),
                 alt.Tooltip("p05:Q", format=".2f"), alt.Tooltip("p95:Q", format=".2f")])
    st.altair_chart((rango + punto).properties(height=max(240, 24 * len(e))).configure_axisY(labelLimit=220),
                    width="stretch")

    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("#### Por categoría")
        st.dataframe(tabla("categorias").round(2), hide_index=True, width="stretch", column_config={
            "categoria": "Categoría", "elasticidad_media": "Elasticidad media", "dispersion": "Dispersión entre marcas",
            "sustitucion": "Sustitución", "encarte": "Encarte (log)", "post_1": "Caída semana 1",
            "post_2": "Caída semana 2"})
    with c2:
        st.markdown("#### Por formato")
        st.dataframe(tabla("formatos").round(2), hide_index=True, width="stretch",
                     column_config={"formato": "Formato", "multiplicador": "Multiplicador de sensibilidad"})

# ----------------------------------------------------------------- ventas

with tab_ventas:
    c1, c2 = st.columns([1, 2])
    with c1:
        cat_v = st.selectbox("Categoría ", m.categorias, index=m.categorias.index("Detergentes"))
        sku_v = st.selectbox("Producto ", SKUS[SKUS.categoria == cat_v].index,
                             format_func=lambda s: f"{s} · {SKUS.loc[s, 'descripcion']}")
    j = list(m.skus.id_sku).index(sku_v)
    serie = pd.DataFrame({"semana": m.semanas, "unidades": m.unidades[:, :, j].sum(0),
                          "precio": m.precio[:, j], "en_promo": m.precio[:, j] < m.regular[:, j] - 1e-9})
    serie["etiqueta"] = serie.semana.map(dia_mes)
    orden_x = serie.etiqueta.tolist()
    x = alt.X("etiqueta:O", title=None, sort=orden_x,
              axis=alt.Axis(values=orden_x[::8], labelAngle=0))
    linea = alt.Chart(serie).mark_line(color=GRIS, strokeWidth=1.6).encode(
        x=x, y=alt.Y("unidades:Q", title="unidades por semana", scale=alt.Scale(zero=False, nice=True)))
    promo = alt.Chart(serie[serie.en_promo]).mark_circle(size=70, color=ACENTO).encode(
        x=x, y="unidades:Q",
        tooltip=["etiqueta", alt.Tooltip("unidades:Q", format=",.0f"), alt.Tooltip("precio:Q", format=".2f")])
    st.altair_chart((linea + promo).properties(height=320), width="stretch")
    st.caption("En cian, las semanas en promoción. En los productos que se guardan en casa, como detergente o "
               "papel, se ve la caída de las semanas siguientes.")
