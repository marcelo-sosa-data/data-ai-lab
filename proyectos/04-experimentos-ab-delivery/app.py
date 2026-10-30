"""
Tablero de experimentos: catálogo con veredictos, lectura de cada experimento,
estudio A/A y planificación de duración.

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

from experimentos.analisis import leer  # noqa: E402
from experimentos.calendario import etiqueta_dia, rango  # noqa: E402
from experimentos.catalogo import DIAS_PRE, EXPERIMENTOS, METRICAS, por_id  # noqa: E402
from experimentos.estadistica import n_necesario  # noqa: E402
from experimentos.reporte import readout  # noqa: E402
from experimentos.rutas import ruta_db, ruta_resultados  # noqa: E402

st.set_page_config(page_title="experimentos · Chasqui", page_icon=":material/science:", layout="wide")

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
.veredicto { font-family: 'JetBrains Mono', monospace; font-size: .95rem; border-radius: 8px; padding: 12px 16px;
             border: 1px solid #1F2A36; background: #0F151C; margin: .2rem 0 .8rem 0; color: #D6DEE6; }
.veredicto b { text-transform: uppercase; letter-spacing: .06em; margin-right: .6rem; }
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO = "#22D3EE"
GRIS = "#7D8B99"
GRIS_OSCURO = "#46535F"
ROJO = "#F87171"
VERDE = "#34D399"
AMBAR = "#FBBF24"
VIOLETA = "#A78BFA"
COLOR_VEREDICTO = {"lanzar": VERDE, "no lanzar": ROJO, "extender": AMBAR, "invalidar": VIOLETA}


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


DB, RES = ruta_db(), ruta_resultados()
if not DB.exists() or not RES.exists():
    st.error("Faltan los datos o los resultados.", icon=":material/database:")
    st.code("python -m experimentos todo", language="bash")
    st.stop()


@st.cache_data(show_spinner=False)
def tabla(nombre: str) -> pd.DataFrame:
    con = duckdb.connect(str(RES), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {nombre}").df()
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def markdown_readout(id_exp: str) -> str:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        return readout(leer(con, por_id(id_exp)))
    finally:
        con.close()


RESUMEN = tabla("resumen")
CORRIDA = tabla("corrida").iloc[0]
MET, SEG, SEM, SEC = tabla("metricas"), tabla("segmentos"), tabla("semanas"), tabla("secuencial")
GUA, SRMV = tabla("guardrails"), tabla("srm_version")


def pct(x: float, signo: bool = True) -> str:
    return f"{x:+.1%}" if signo else f"{x:.1%}"


def forest(df: pd.DataFrame, etiqueta: str, color: str = "color:N", alto: int = 220, dominio=None) -> alt.Chart:
    """Efecto relativo con su IC 95%, una fila por métrica o experimento."""
    orden = list(df[etiqueta])
    base = alt.Chart(df).encode(y=alt.Y(f"{etiqueta}:N", sort=orden, title=None,
                                        axis=alt.Axis(labelLimit=260, labelFontSize=11)))
    escala = alt.Scale(domain=dominio) if dominio else alt.Scale(zero=False)
    reglas = base.mark_rule(strokeWidth=2.2).encode(
        x=alt.X("relativo_bajo:Q", title="efecto relativo (IC 95%)", axis=alt.Axis(format="+%"), scale=escala),
        x2="relativo_alto:Q", color=alt.Color(color, scale=None))
    puntos = base.mark_point(filled=True, size=70, opacity=1).encode(
        x="relativo:Q", color=alt.Color(color, scale=None),
        tooltip=[alt.Tooltip(f"{etiqueta}:N", title=" "), alt.Tooltip("relativo:Q", format="+.2%", title="efecto"),
                 alt.Tooltip("relativo_bajo:Q", format="+.2%", title="IC bajo"),
                 alt.Tooltip("relativo_alto:Q", format="+.2%", title="IC alto"),
                 alt.Tooltip("p_valor:Q", format=".4f", title="p")])
    texto = base.mark_text(align="left", dx=8, dy=-9, font="JetBrains Mono", fontSize=10.5, color="#D6DEE6"
                           ).encode(x="relativo:Q", text="txt:N")
    cero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=GRIS_OSCURO, strokeDash=[4, 4]).encode(x="x:Q")
    return (cero + reglas + puntos + texto).properties(height=alto)


# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Chasqui")
    st.caption("App de delivery ficticia en Lima, Arequipa, Trujillo y Piura · datos sintéticos")
    id_exp = st.radio("Experimento", RESUMEN.id_experimento,
                      format_func=lambda i: f"{i} · {RESUMEN.set_index('id_experimento').nombre[i]}", index=1)
    st.subheader("Última corrida")
    st.markdown(f'<div class="nota">{pd.Timestamp(CORRIDA.fecha):%d/%m/%Y %H:%M}<br>'
                f'<b>{int(CORRIDA.experimentos)}</b> experimentos · {CORRIDA.segundos:.1f} s</div>',
                unsafe_allow_html=True)

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> experimentos</p>', unsafe_allow_html=True)
st.caption("Lectura de los experimentos A/B de 2026 con una regla de decisión fija: SRM, CUPED, método delta, "
           "guardrails de no inferioridad y lectura secuencial con mSPRT.")
st.markdown(
    f'<div class="estado"><b>●</b> duckdb · {DB.name} · {int(RESUMEN.n_control.sum() + RESUMEN.n_tratamiento.sum()):,} '
    f'exposiciones · unidad: usuario · CUPED con {DIAS_PRE} días previos</div>', unsafe_allow_html=True)
st.write("")

aa = tabla("aa_curva")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Experimentos", f"{len(RESUMEN)}")
m2.metric("Para lanzar", f"{int((RESUMEN.veredicto == 'lanzar').sum())}",
          help="Primaria positiva y todos los guardrails dentro de su margen.")
m3.metric("Invalidados por SRM", f"{int((RESUMEN.veredicto == 'invalidar').sum())}")
m4.metric("Varianza con CUPED", f"-{RESUMEN.reduccion_varianza[RESUMEN.reduccion_varianza > 0].mean():.0%}",
          help="Reducción promedio en la varianza de la métrica primaria.")
m5.metric("Falsos positivos", pct(aa.mirando_cada_dia.iloc[-1], False),
          f"mSPRT {aa.msprt_cada_dia.iloc[-1]:.1%}", delta_color="off", delta_arrow="off",
          help="Estudio A/A: repartos al azar sin efecto real, leídos los 28 días con p < 0.05.")

st.write("")
tab_cat, tab_exp, tab_aa, tab_plan, tab_md = st.tabs([
    ":material/view_list: Catálogo", ":material/science: Experimento", ":material/visibility: Mirar cada día",
    ":material/straighten: Planificar", ":material/description: Readout",
])

# ----------------------------------------------------------------- catálogo

with tab_cat:
    st.markdown("#### Métrica primaria por experimento")
    r = RESUMEN.copy()
    r["etiqueta"] = r.id_experimento + " · " + r.nombre
    r["color"] = r.veredicto.map(COLOR_VEREDICTO)
    r["txt"] = r.relativo.map(pct) + "  " + r.veredicto
    st.altair_chart(forest(r, "etiqueta", alto=240), width="stretch")
    st.markdown('<div class="nota">Efecto relativo con CUPED e IC 95%. Color por veredicto: '
                f'<b style="color:{VERDE}">lanzar</b> · <b style="color:{ROJO}">no lanzar</b> · '
                f'<b style="color:{VIOLETA}">invalidar</b> (el efecto de un experimento con SRM no se lee).</div>',
                unsafe_allow_html=True)
    st.write("")
    vista = r[["id_experimento", "nombre", "inicio", "primaria", "n_control", "n_tratamiento", "p_srm",
               "relativo", "veredicto", "dia_parada_msprt", "motivo"]].copy()
    vista["inicio"] = vista.inicio.map(lambda d: f"{etiqueta_dia(d)} {pd.Timestamp(d).year}")
    vista["primaria"] = vista.primaria.map(lambda m: METRICAS[m]["nombre"])
    vista["relativo"] *= 100
    vista["dia_parada_msprt"] = vista.dia_parada_msprt.map(lambda d: "-" if pd.isna(d) else f"día {int(d)}")
    st.dataframe(vista, hide_index=True, width="stretch", column_config={
        "id_experimento": "exp.", "nombre": "nombre", "inicio": "inicio", "primaria": "primaria",
        "n_control": st.column_config.NumberColumn("control", format="localized"),
        "n_tratamiento": st.column_config.NumberColumn("tratamiento", format="localized"),
        "p_srm": st.column_config.NumberColumn("p SRM", format="%.2g"),
        "relativo": st.column_config.NumberColumn("efecto", format="%+.1f%%"),
        "veredicto": "veredicto",
        "dia_parada_msprt": st.column_config.TextColumn("parada mSPRT",
                                                        help="Primer día, desde el 7, con p siempre válido < 0.05"),
        "motivo": st.column_config.TextColumn("motivo", width="large"),
    })

# ----------------------------------------------------------------- experimento

with tab_exp:
    exp = por_id(id_exp)
    res = RESUMEN.set_index("id_experimento").loc[id_exp]
    st.markdown(f"#### {exp.id} · {exp.nombre} · {rango(exp.inicio, exp.fin)}")
    st.caption(exp.hipotesis)
    st.markdown(f'<div class="veredicto"><b style="color:{COLOR_VEREDICTO[res.veredicto]}">{res.veredicto}</b>'
                f'{res.motivo}</div>', unsafe_allow_html=True)

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Expuestos", f"{res.n_control + res.n_tratamiento:,}",
              f"{res.n_tratamiento / (res.n_control + res.n_tratamiento):.1%} en tratamiento", delta_color="off",
              delta_arrow="off")
    e2.metric("p SRM", f"{res.p_srm:.2g}", "desbalance" if res.p_srm < 0.001 else "ok",
              delta_color="inverse" if res.p_srm < 0.001 else "off", delta_arrow="off")
    e3.metric("Efecto primaria", pct(res.relativo), f"IC {pct(res.relativo_bajo)} a {pct(res.relativo_alto)}",
              delta_color="off", delta_arrow="off")
    e4.metric("Varianza con CUPED", f"-{res.reduccion_varianza:.0%}", help=f"Covariable: la misma métrica en los "
                                                                         f"{DIAS_PRE} días previos.")

    col_a, col_b = st.columns([1.15, 1])
    with col_a:
        st.markdown("#### Todas las métricas")
        mm = MET[MET.id_experimento == id_exp].copy()
        mm["etiqueta"] = mm.nombre + " · " + mm.metodo
        mm["color"] = mm.rol.map({"primaria": ACENTO, "guardrail": AMBAR, "secundaria": GRIS})
        mm.loc[mm.metodo == "welch", "color"] = GRIS_OSCURO
        mm["txt"] = mm.relativo.map(pct)
        st.altair_chart(forest(mm, "etiqueta", alto=330), width="stretch")
        st.markdown(f'<div class="nota"><b style="color:{ACENTO}">primaria</b> · '
                    f'<b style="color:{AMBAR}">guardrail</b> · <b style="color:{GRIS}">secundaria</b> · '
                    f'<b style="color:{GRIS_OSCURO}">sin CUPED</b>, para comparar el ancho del intervalo. '
                    'Las de ratio (ticket, cancelación) van con método delta.</div>', unsafe_allow_html=True)
    with col_b:
        if res.veredicto == "invalidar":
            st.markdown("#### Dónde está el desbalance")
            sv = SRMV[SRMV.id_experimento == id_exp].drop(columns="id_experimento")
            sv["p_srm"] = sv.p_srm.map(lambda x: f"{x:.1e}" if x < 0.001 else f"{x:.2f}")
            st.dataframe(sv, hide_index=True, width="stretch", column_config={
                "version_app": "versión",
                "control": st.column_config.NumberColumn("control", format="localized"),
                "tratamiento": st.column_config.NumberColumn("tratamiento", format="localized"),
                "pct_tratamiento": st.column_config.ProgressColumn("% tratamiento", format="percent",
                                                                   min_value=0, max_value=1),
                "p_srm": st.column_config.TextColumn("p SRM"),
            })
            st.caption("Si el desbalance vive en un segmento, apunta al bug. Aquí: el evento de exposición del "
                       "tratamiento en Android antiguo.")
        st.markdown("#### Guardrails")
        gg = GUA[GUA.id_experimento == id_exp].copy()
        if len(gg):
            gg["metrica"] = gg.metrica.map(lambda m: METRICAS[m]["nombre"])
            gg["margen"] *= 100
            gg["peor_caso"] *= 100
            st.dataframe(gg[["metrica", "margen", "peor_caso", "estado"]], hide_index=True, width="stretch",
                         column_config={
                             "metrica": "métrica",
                             "margen": st.column_config.NumberColumn("daño tolerado", format="%.0f%%"),
                             "peor_caso": st.column_config.NumberColumn("peor caso del IC", format="%+.1f%%",
                                                                        help="Positivo = daño"),
                             "estado": "estado"})
        else:
            st.caption("No se evalúan: el experimento está invalidado.")
        st.markdown(f"#### Segmentos · {METRICAS[exp.primaria]['nombre']}")
        sg = SEG[SEG.id_experimento == id_exp][["segmento", "n_control", "relativo", "relativo_bajo",
                                                "relativo_alto", "q_valor"]].copy()
        for c in ("relativo", "relativo_bajo", "relativo_alto"):
            sg[c] *= 100
        st.dataframe(sg, hide_index=True, width="stretch", column_config={
            "n_control": st.column_config.NumberColumn("usuarios control", format="localized"),
            "relativo": st.column_config.NumberColumn("efecto", format="%+.1f%%"),
            "relativo_bajo": st.column_config.NumberColumn("IC bajo", format="%+.1f%%"),
            "relativo_alto": st.column_config.NumberColumn("IC alto", format="%+.1f%%"),
            "q_valor": st.column_config.NumberColumn("q (BH)", format="%.3f",
                                                     help="p-valor corregido por Benjamini-Hochberg"),
        })

    col_c, col_d = st.columns([1.4, 1])
    with col_c:
        st.markdown("#### Lo que se veía cada mañana")
        sq = SEC[SEC.id_experimento == id_exp].copy()
        sq["dia_txt"] = sq.fecha.map(etiqueta_dia)
        orden = list(sq.dia_txt)
        eje = alt.X("dia_txt:O", sort=orden, title=None, axis=alt.Axis(values=orden[::3], labelAngle=0))
        # los primeros días el intervalo es enorme: la escala se fija desde el día 5 y se recorta lo demás
        ref = sq[sq.dia >= 5]
        margen_y = 0.15 * (ref.sv_alto.max() - ref.sv_bajo.min())
        escala_y = alt.Scale(domain=[min(ref.sv_bajo.min(), 0) - margen_y, ref.sv_alto.max() + margen_y], clamp=True)
        banda_sv = alt.Chart(sq).mark_area(color=ACENTO, opacity=0.10, clip=True).encode(
            x=eje, y=alt.Y("sv_bajo:Q", scale=escala_y), y2="sv_alto:Q")
        banda = alt.Chart(sq).mark_area(color=GRIS, opacity=0.18, clip=True).encode(
            x=eje, y=alt.Y("ic_bajo:Q", scale=escala_y), y2="ic_alto:Q")
        linea = alt.Chart(sq).mark_line(color=ACENTO, strokeWidth=2.2, point=alt.OverlayMarkDef(size=22)).encode(
            x=eje, y=alt.Y("relativo:Q", title="efecto relativo acumulado", axis=alt.Axis(format="+%", tickCount=6),
                           scale=escala_y),
            tooltip=[alt.Tooltip("dia_txt:N", title="día"), alt.Tooltip("relativo:Q", format="+.2%", title="efecto"),
                     alt.Tooltip("p_clasico:Q", format=".4f", title="p clásico"),
                     alt.Tooltip("p_siempre_valido:Q", format=".4f", title="p siempre válido")])
        cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=GRIS_OSCURO, strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart((banda_sv + banda + cero + linea).properties(height=300), width="stretch")
        parada = res.dia_parada_msprt
        st.markdown(
            '<div class="nota">Banda gris: IC 95% clásico (válido solo si se mira una vez) · '
            f'<b style="color:{ACENTO}">banda cian</b>: intervalo siempre válido del mSPRT, que se puede mirar a diario. '
            + (f"Con al menos una semana completa, el mSPRT permitía parar el <b>día {int(parada)}</b>."
               if pd.notna(parada) else "El mSPRT no bajó de 0.05 en la ventana.") + "</div>", unsafe_allow_html=True)
    with col_d:
        st.markdown("#### Efecto por semana desde la exposición")
        sw = SEM[SEM.id_experimento == id_exp].copy()
        sw["etq"] = sw.semana.map(lambda s: "sem 2 en adelante" if s == "2+" else f"semana {s}")
        sw["color"] = [ACENTO if s == "1" else (AMBAR if s == "2+" else GRIS) for s in sw.semana]
        sw["txt"] = sw.relativo.map(pct)
        st.altair_chart(forest(sw, "etq", alto=220), width="stretch")
        st.caption("Cada usuario cuenta desde su propia exposición. La semana 4 solo la completan quienes "
                   "entraron el primer día, por eso su intervalo es ancho.")

# ----------------------------------------------------------------- A/A

with tab_aa:
    res_aa = tabla("aa_resumen").iloc[0]
    st.markdown(f"#### {int(res_aa.repeticiones):,} experimentos A/A con usuarios reales · "
                f"{rango(res_aa.inicio, res_aa.fin)} · {int(res_aa.usuarios):,} usuarios")
    curva = aa.melt(id_vars="dia", value_vars=["mirando_cada_dia", "una_mirada", "msprt_cada_dia"],
                    var_name="regla", value_name="fp")
    nombres = {"mirando_cada_dia": "p < 0.05 algún día (mirando a diario)", "una_mirada": "una sola mirada ese día",
               "msprt_cada_dia": "mSPRT, mirando a diario"}
    curva["regla"] = curva.regla.map(nombres)
    g = alt.Chart(curva).mark_line(strokeWidth=2.4, point=alt.OverlayMarkDef(size=20)).encode(
        x=alt.X("dia:Q", title="días de experimento", scale=alt.Scale(domain=[1, 28]), axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("fp:Q", title="falsos positivos", axis=alt.Axis(format="%")),
        color=alt.Color("regla:N", scale=alt.Scale(domain=list(nombres.values()), range=[ROJO, GRIS, ACENTO]),
                        legend=alt.Legend(orient="top", title=None, labelLimit=320)),
        tooltip=["regla", "dia", alt.Tooltip("fp:Q", format=".1%")])
    nominal = alt.Chart(pd.DataFrame({"y": [0.05]})).mark_rule(color=GRIS_OSCURO, strokeDash=[4, 4]).encode(y="y:Q")
    st.altair_chart((nominal + g).properties(height=360), width="stretch")
    st.markdown(
        '<div class="nota">Se toman los usuarios activos de un periodo sin experimentos, se reparten al azar en dos '
        'grupos y se leen como si fuera un experimento. No hay efecto real: todo "ganador" es un falso positivo. '
        f'Mirando cada día y parando al primer p < 0.05, al día 28 se declaró ganador en el '
        f'<b>{aa.mirando_cada_dia.iloc[-1]:.1%}</b> de los repartos. Con una sola mirada, '
        f'<b>{aa.una_mirada.iloc[-1]:.1%}</b>; con mSPRT a diario, <b>{aa.msprt_cada_dia.iloc[-1]:.1%}</b>.</div>',
        unsafe_allow_html=True)

# ----------------------------------------------------------------- planificar

with tab_plan:
    plan = tabla("planificacion")
    c1, c2 = st.columns([1, 1.3])
    with c1:
        st.markdown("#### Antes de lanzar")
        met = st.segmented_control("Métrica", ["pedidos", "gmv"], default="pedidos",
                                   format_func=lambda m: METRICAS[m]["nombre"]) or "pedidos"
        objetivo = st.slider("Efecto que se quiere detectar", 1.0, 8.0, 3.0, 0.5, format="%.1f%%") / 100
        reparto = st.slider("Tráfico en tratamiento", 10, 50, 50, 5, format="%d%%") / 100
        p = plan[plan.metrica == met].copy()
        p["n_grupo"] = p.usuarios * reparto
        fila = p.iloc[-1]
        n_req = n_necesario(fila.media, fila.sd, objetivo, fila.rho)
        n_req_sin = n_necesario(fila.media, fila.sd, objetivo)
        k1, k2 = st.columns(2)
        k1.metric("Por grupo con CUPED", f"{n_req:,}")
        k2.metric("Sin CUPED", f"{n_req_sin:,}", f"{n_req / n_req_sin - 1:+.0%} con CUPED", delta_color="off",
                  delta_arrow="off")
        alcanza = p[p.n_grupo >= n_req]
        if len(alcanza):
            st.success(f"Alcanza con {int(alcanza.semanas.iloc[0])} semana(s) al {reparto:.0%} de tráfico.",
                       icon=":material/check_circle:")
        else:
            st.warning(f"En 4 semanas entran {int(fila.n_grupo):,} usuarios por grupo: no alcanza para "
                       f"{objetivo:.1%}. Hay que subir el tráfico, alargar o aceptar un efecto mínimo mayor.",
                       icon=":material/warning:")
        st.caption("Varianza, tráfico y correlación con el periodo previo medidos en un periodo sin experimentos "
                   "(80% de potencia, α = 5%). Los usuarios nuevos por semana bajan: duplicar la duración no "
                   "duplica la muestra.")
    with c2:
        st.markdown("#### Efecto mínimo detectable según la duración")
        pp = plan[plan.metrica == met].melt(id_vars=["semanas", "usuarios"], value_vars=["mde_sin_cuped",
                                                                                       "mde_con_cuped"],
                                            var_name="caso", value_name="mde")
        pp["caso"] = pp.caso.map({"mde_sin_cuped": "sin CUPED", "mde_con_cuped": "con CUPED"})
        g = alt.Chart(pp).mark_line(strokeWidth=2.4, point=alt.OverlayMarkDef(size=40)).encode(
            x=alt.X("semanas:O", title="semanas (50/50)", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mde:Q", title="MDE relativo", axis=alt.Axis(format="%"), scale=alt.Scale(zero=False)),
            color=alt.Color("caso:N", scale=alt.Scale(domain=["sin CUPED", "con CUPED"], range=[GRIS, ACENTO]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["caso", "semanas", alt.Tooltip("usuarios:Q", format=","), alt.Tooltip("mde:Q", format=".2%")])
        obj = alt.Chart(pd.DataFrame({"y": [objetivo]})).mark_rule(color=AMBAR, strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart((g + obj).properties(height=300), width="stretch")
        pv = plan[plan.metrica == met][["semanas", "usuarios", "rho", "mde_sin_cuped", "mde_con_cuped"]].copy()
        pv[["mde_sin_cuped", "mde_con_cuped"]] *= 100
        st.dataframe(pv, hide_index=True, width="stretch", column_config={
            "usuarios": st.column_config.NumberColumn("usuarios expuestos", format="localized"),
            "rho": st.column_config.NumberColumn("ρ con el pre", format="%.2f"),
            "mde_sin_cuped": st.column_config.NumberColumn("MDE sin CUPED", format="%.1f%%"),
            "mde_con_cuped": st.column_config.NumberColumn("MDE con CUPED", format="%.1f%%")})

# ----------------------------------------------------------------- readout

with tab_md:
    md = markdown_readout(id_exp)
    st.download_button("Descargar Markdown", md.encode("utf-8"), f"{id_exp}.md", "text/markdown",
                       icon=":material/download:")
    with st.container(border=True):
        st.markdown(md)
