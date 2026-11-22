"""
Tablero del análisis de trámites.

    streamlit run app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from tramites import catalogos as K  # noqa: E402
from tramites import resultados as Res  # noqa: E402
from tramites.calendario import etiqueta_dia  # noqa: E402
from tramites.descubrimiento import a_dot  # noqa: E402

st.set_page_config(page_title="Trámites · Universidad Mirasol", page_icon=":material/account_tree:",
                   layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
[data-testid="stMetricDelta"] { font-family: 'JetBrains Mono', monospace; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.estado { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #7D8B99;
          border: 1px solid #1F2A36; border-radius: 6px; padding: 6px 10px; display: inline-block; }
.estado b { color: #34D399; font-weight: 600; }
.nota { color: #7D8B99; font-size: .85rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

RUTA = Path(os.getenv("TRAMITES_RESULTADOS", RAIZ / "datos" / "resultados.duckdb"))
ACENTO, GRIS, TEXTO, FONDO = "#22D3EE", "#4B5A6A", "#D6DEE6", "#0B0F14"
CORTO = {K.CONVALIDACION: "Convalidación", K.RETIRO: "Retiro"}
METRICAS = {"mediana_dias": "Mediana (días)", "p90_dias": "p90 (días)",
            "pct_fuera_plazo": "Fuera de plazo", "pct_excepcion": "Con excepción"}


def tema():
    return {"config": {
        "background": FONDO, "view": {"stroke": None},
        "axis": {"labelColor": "#9AA7B4", "titleColor": "#7D8B99", "gridColor": "#1A222C",
                 "domainColor": "#2A3644", "tickColor": "#2A3644", "labelFont": "Inter",
                 "titleFont": "Inter", "titleFontWeight": 500, "labelLimit": 240},
        "legend": {"labelColor": "#9AA7B4", "titleColor": "#7D8B99", "labelFont": "Inter",
                   "labelLimit": 260},
        "title": {"color": TEXTO, "font": "Inter", "anchor": "start", "fontWeight": 500},
    }}


if hasattr(alt, "theme"):  # Altair 5.5 o más nuevo
    alt.theme.register("oscuro", enable=True)(tema)
else:
    alt.themes.register("oscuro", tema)
    alt.themes.enable("oscuro")


@st.cache_data(show_spinner=False)
def tabla(nombre: str) -> pd.DataFrame:
    return Res.leer(RUTA, nombre)


@st.cache_data(show_spinner=False)
def metadatos() -> dict:
    return Res.meta(RUTA)


if not RUTA.exists():
    st.error("No encuentro los resultados. Corre primero: python -m tramites todo", icon=":material/error:")
    st.stop()

disponibles = Res.tablas(RUTA)
meta = metadatos()
casos = tabla("casos")

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Universidad Mirasol")
    st.caption("Sistema de trámites · ene a nov 2026 · datos sintéticos")
    tipo = st.radio("Trámite", [K.CONVALIDACION, K.RETIRO], format_func=lambda t: CORTO[t])
    st.subheader("Mapa del proceso")
    metrica = st.radio("Etiqueta de los arcos", ["Trámites", "Mediana de tiempo"], horizontal=True)
    minimo = st.slider("Ocultar arcos con menos de", 0.0, 10.0, 2.0, 0.5, format="%.1f%%") / 100
    st.caption("Los arcos en cian son el 20% más lento.")

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> tramites</p>', unsafe_allow_html=True)
st.caption("Cómo fluyen de verdad las convalidaciones y los retiros, dónde se va el tiempo y qué "
           "pasaría si se cambia el orden de las aprobaciones.")
lec = meta.get("lectura", {})
st.markdown(
    f'<div class="estado"><b>●</b> {lec.get("eventos", 0):,} eventos · {len(casos):,} trámites · '
    f'{lec.get("duplicados", 0)} duplicados quitados · {lec.get("abiertos", 0)} abiertos al corte</div>',
    unsafe_allow_html=True)
st.write("")

c = casos[casos["tipo"] == tipo]
atendidos = c[c["estado"] == "Atendido"]
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Trámites", f"{len(c):,}")
k2.metric("Mediana", f"{atendidos['duracion_dias'].median():.1f} días")
k3.metric("p90", f"{atendidos['duracion_dias'].quantile(.9):.1f} días")
k4.metric(f"Fuera de plazo ({K.PLAZO_DIAS[tipo]} d háb.)", f"{atendidos['fuera_plazo'].mean():.1%}")
if tipo == K.RETIRO:
    k5.metric("Con resolución de excepción", f"{c['excepcion'].mean():.1%}")
else:
    k5.metric("Con reproceso", f"{c['reproceso'].mean():.1%}")

t_mapa, t_tiempo, t_control, t_esc = st.tabs([
    ":material/account_tree: Proceso real", ":material/schedule: Dónde se va el tiempo",
    ":material/rule: Conformidad y controles", ":material/science: Escenarios"])

# ----------------------------------------------------------------- proceso real

with t_mapa:
    arcos = tabla("arcos")
    arcos = arcos[arcos["tipo"] == tipo]
    st.graphviz_chart(a_dot(arcos, minimo, "n" if metrica == "Trámites" else "tiempo"),
                      width="stretch")
    st.caption("Grafo de seguimiento directo descubierto del log con PM4Py. El tiempo es la mediana "
               "en horas calendario entre el fin de una actividad y el de la siguiente.")
    v = tabla("variantes")
    v = v[v["tipo"] == tipo].head(10)
    st.markdown("**Variantes más frecuentes**")
    st.dataframe(v[["rango", "variante", "tramites", "pct", "mediana_dias"]], hide_index=True,
                 width="stretch", column_config={
                     "rango": st.column_config.NumberColumn("#", width="small"),
                     "variante": st.column_config.TextColumn("Secuencia", width="large"),
                     "tramites": st.column_config.NumberColumn("Trámites", format="localized"),
                     "pct": st.column_config.NumberColumn("% del tipo", format="percent"),
                     "mediana_dias": st.column_config.NumberColumn("Mediana días", format="%.1f")})

# ----------------------------------------------------------------- tiempo

with t_tiempo:
    izq, der = st.columns(2)
    area = tabla("por_area")
    area = area[area["tipo"] == tipo].sort_values("en_area_media_h", ascending=False)
    largo = area.melt(id_vars="area", value_vars=["atencion_media_h", "en_area_media_h"],
                      var_name="medida", value_name="horas").dropna()
    largo["medida"] = largo["medida"].map({"atencion_media_h": "Lo que reporta el área",
                                           "en_area_media_h": "Lo que el trámite pasa ahí"})
    with izq:
        st.markdown("**Horas hábiles por visita a cada área**")
        g = alt.Chart(largo).mark_bar(cornerRadiusEnd=3, height=12).encode(
            y=alt.Y("area:N", title=None, sort=list(area["area"])),
            yOffset=alt.YOffset("medida:N", sort=["Lo que reporta el área", "Lo que el trámite pasa ahí"]),
            x=alt.X("horas:Q", title="horas hábiles"),
            color=alt.Color("medida:N", scale=alt.Scale(range=[GRIS, ACENTO]), legend=alt.Legend(
                orient="bottom", title=None)),
            tooltip=["area", "medida", alt.Tooltip("horas:Q", format=".1f")])
        st.altair_chart(g.properties(height=300), width="stretch")
        st.caption("Tesorería y Decanato no registran hora de inicio: solo se ve el tiempo total.")
    rep = tabla("reparto")
    rep = rep[rep["tipo"] == tipo]
    with der:
        st.markdown("**De qué está hecho el tiempo de un trámite atendido**")
        g = alt.Chart(rep).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("componente:N", title=None, sort="-x"),
            x=alt.X("pct:Q", title=None, axis=alt.Axis(format="%")),
            color=alt.condition(alt.datum.componente == "Trabajo de las áreas", alt.value(ACENTO),
                                alt.value(GRIS)),
            tooltip=["componente", alt.Tooltip("pct:Q", format=".1%")])
        st.altair_chart(g.properties(height=300), width="stretch")

    st.markdown("**Mediana de días por semana de registro**")
    sem = atendidos.assign(semana=atendidos["registro"].dt.to_period("W").dt.start_time)
    sem = sem.groupby("semana").agg(mediana=("duracion_dias", "median"), n=("id_tramite", "size")).reset_index()
    sem = sem[sem["n"] >= 8]
    # etiquetas armadas en Python para que el navegador no corra las fechas por zona horaria
    sem["etiqueta"] = sem["semana"].map(etiqueta_dia)
    base = alt.Chart(sem).encode(
        x=alt.X("etiqueta:O", title="semana que empieza el", sort=list(sem["etiqueta"]),
                axis=alt.Axis(labelAngle=-45, labelOverlap=True)),
        y=alt.Y("mediana:Q", title="días", scale=alt.Scale(zero=False, nice=True)),
        tooltip=[alt.Tooltip("etiqueta:N", title="semana"), alt.Tooltip("mediana:Q", format=".1f"), "n"])
    st.altair_chart((base.mark_line(color=ACENTO, strokeWidth=2.5) + base.mark_circle(color=ACENTO, size=40))
                    .properties(height=280), width="stretch")
    aus = tabla("ausencias")
    if len(aus):
        st.markdown("**Semanas sin atención en Dirección**")
        fecha = {c: st.column_config.DateColumn(t, format="DD/MM/YYYY") for c, t in
                 (("desde", "Desde"), ("hasta", "Hasta"), ("normal_desde", "Espera normal desde"))}
        st.dataframe(aus, hide_index=True, width="stretch", column_config={
            "carrera": "Carrera", "dias_habiles": "Días hábiles",
            "tramites_en_espera": "Trámites esperando", **fecha})
        st.caption("Cada fila es un director sin actividad en el log teniendo expedientes en bandeja. "
                   "Esas esperas no entran a la estimación de la simulación.")

# ----------------------------------------------------------------- conformidad

with t_control:
    conf = tabla("conformidad").set_index("tipo")
    ctrl = tabla("controles")
    a, b = st.columns([1, 2])
    a.metric("Trazas que siguen el reglamento", f"{conf.loc[tipo, 'conformes']:.1%}")
    a.caption("Alineamiento de cada trámite atendido contra el modelo del reglamento escrito como "
              "árbol de proceso.")
    b.dataframe(ctrl, hide_index=True, width="stretch", column_config={
        "control": st.column_config.TextColumn("Control", width="large"),
        "evaluados": st.column_config.NumberColumn("Evaluados", format="localized"),
        "casos": st.column_config.NumberColumn("Casos", format="localized"),
        "pct": st.column_config.NumberColumn("%", format="percent")})

    st.markdown("**Trámites con desvío**")
    cols = {"sin_pago": "Sin pago verificado", "sin_revision": "Sin revisión de Secretaría",
            "sin_visto_bueno": "Sin visto bueno"}
    elegido = st.segmented_control("Control", list(cols), format_func=cols.get, default="sin_pago")
    if elegido:
        d = c[c[elegido] == 1].sort_values("registro")
        st.dataframe(d[["id_tramite", "codigo_alumno", "nombre_alumno", "carrera", "sede", "registro",
                        "estado"]], hide_index=True, width="stretch", column_config={
            "id_tramite": "Trámite", "codigo_alumno": "Código", "nombre_alumno": "Alumno",
            "carrera": "Carrera", "sede": "Sede",
            "registro": st.column_config.DatetimeColumn("Registro", format="DD/MM/YYYY"),
            "estado": "Estado"})
        st.download_button("Descargar CSV", d.to_csv(index=False).encode("utf-8-sig"),
                           f"desvio_{elegido}.csv", "text/csv", icon=":material/download:")

# ----------------------------------------------------------------- escenarios

with t_esc:
    if "escenarios" not in disponibles:
        st.info("Corre python -m tramites simular para ver los escenarios.", icon=":material/info:")
        st.stop()
    esc = tabla("escenarios")
    e = esc[esc["tipo"] == tipo].copy()
    orden = [K.ESCENARIOS[k][0] for k in K.ESCENARIOS]
    st.markdown("**Mediana de días estimada por escenario (trámites de jul a oct)**")
    g = alt.Chart(e).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("nombre:N", title=None, sort=orden),
        x=alt.X("estimado_mediana_dias:Q", title="días"),
        color=alt.condition(alt.datum.escenario == "actual", alt.value(GRIS), alt.value(ACENTO)),
        tooltip=["nombre", alt.Tooltip("estimado_mediana_dias:Q", title="mediana", format=".1f"),
                 alt.Tooltip("estimado_p90_dias:Q", title="p90", format=".1f"),
                 alt.Tooltip("estimado_pct_fuera_plazo:Q", title="fuera de plazo", format=".1%")])
    st.altair_chart(g.properties(height=230), width="stretch")
    st.caption("Los escenarios son acumulativos. Estimado = observado en el proceso actual por el cambio "
               "relativo que da la simulación contra el actual simulado.")
    vista = e[["nombre", "estimado_mediana_dias", "estimado_p90_dias", "estimado_pct_fuera_plazo"]
              + (["estimado_pct_excepcion"] if tipo == K.RETIRO else [])]
    st.dataframe(vista, hide_index=True, width="stretch", column_config={
        "nombre": "Escenario",
        "estimado_mediana_dias": st.column_config.NumberColumn("Mediana días", format="%.1f"),
        "estimado_p90_dias": st.column_config.NumberColumn("p90 días", format="%.1f"),
        "estimado_pct_fuera_plazo": st.column_config.NumberColumn("Fuera de plazo", format="percent"),
        "estimado_pct_excepcion": st.column_config.NumberColumn("Con excepción", format="percent")})

    izq, der = st.columns(2)
    with izq:
        st.markdown("**Validación: proceso actual simulado contra observado**")
        val = tabla("validacion")
        val = val[val["tipo"] == tipo].assign(metrica=lambda d: d["metrica"].map(METRICAS))
        st.dataframe(val[["metrica", "observado", "simulado", "error_relativo"]], hide_index=True,
                     width="stretch", column_config={
                         "metrica": "Indicador",
                         "observado": st.column_config.NumberColumn("Observado", format="%.3f"),
                         "simulado": st.column_config.NumberColumn("Simulado", format="%.3f"),
                         "error_relativo": st.column_config.NumberColumn("Error", format="percent")})
    with der:
        st.markdown("**Carga de trabajo por escenario**")
        ex = tabla("escenarios_extras")
        st.dataframe(ex[["nombre", "revisiones_secretaria_por_conv", "evaluaciones_en_archivados",
                         "pct_retiros_por_direccion"]], hide_index=True, width="stretch", column_config={
            "nombre": "Escenario",
            "revisiones_secretaria_por_conv": st.column_config.NumberColumn("Revisiones Sec./conv.", format="%.2f"),
            "evaluaciones_en_archivados": st.column_config.NumberColumn("Evaluadas y archivadas", format="%.0f"),
            "pct_retiros_por_direccion": st.column_config.NumberColumn("Retiros por Dirección", format="percent")})

    if "contra_verdad" in disponibles:
        st.markdown("**Revisión contra el generador** "
                    '<span class="nota">(solo posible porque los datos son sintéticos)</span>',
                    unsafe_allow_html=True)
        cv = tabla("contra_verdad")
        cv = cv[(cv["tipo"] == tipo) & (cv["escenario"] != "actual")].copy()
        cv["escenario"] = cv["escenario"].map(lambda k: K.ESCENARIOS[k][0])
        cv["metrica"] = cv["metrica"].map(METRICAS)
        st.dataframe(cv[["escenario", "metrica", "estimado", "real", "efecto_estimado", "efecto_real"]],
                     hide_index=True, width="stretch", column_config={
                         "escenario": "Escenario", "metrica": "Indicador",
                         "estimado": st.column_config.NumberColumn("Estimado", format="%.3f"),
                         "real": st.column_config.NumberColumn("Real", format="%.3f"),
                         "efecto_estimado": st.column_config.NumberColumn("Efecto estimado", format="%+.3f"),
                         "efecto_real": st.column_config.NumberColumn("Efecto real", format="%+.3f")})
