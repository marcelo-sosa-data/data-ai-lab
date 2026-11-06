"""
Tablero de alerta temprana: lista de la semana, detalle por alumno, evaluación y supervivencia.

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import duckdb
import numpy as np
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from desercion.resultados import tablas  # noqa: E402
from desercion.rutas import ruta_db, ruta_resultados  # noqa: E402

st.set_page_config(page_title="desercion · Qhapaq Ñan", page_icon=":material/school:", layout="wide")

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
.ficha { font-size: .86rem; color: #9AA7B4; line-height: 1.7; }
.ficha b { color: #D6DEE6; font-weight: 500; }
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO = "#22D3EE"
GRIS = "#7D8B99"
GRIS_OSCURO = "#46535F"
AMBAR = "#FBBF24"
ROJO = "#F87171"
POLITICAS = {"modelo": "LightGBM", "logistica": "Logística", "regla_ordenada": "Regla ordenada",
             "regla_actual": "Regla actual"}
COLORES_POL = [ACENTO, "#A78BFA", AMBAR, GRIS_OSCURO]


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


def consultar(ruta: Path, sql: str, params: list | None = None) -> pd.DataFrame:
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


DB, RES = ruta_db(), ruta_resultados()
if not DB.exists() or not RES.exists():
    st.error("Faltan los datos o los resultados.", icon=":material/database:")
    st.code("python -m desercion todo", language="bash")
    st.stop()


@st.cache_data(show_spinner=False)
def tabla(nombre: str) -> pd.DataFrame:
    return consultar(RES, f"SELECT * FROM {nombre}")


VIG = tabla("vigente").iloc[0]
PART = tabla("particion").iloc[0]
LISTA = tabla("lista")
AUSENTES = tabla("ausentes")
CAPACIDAD = int(PART.capacidad)
SEM = int(VIG.semana)


def eje_semana(valores, titulo=None):
    """Semanas como texto ('s2', 's3', ...): ordinal y sin sorpresas de formato."""
    return alt.X("etiqueta:O", sort=[f"s{v}" if v <= 16 else "entre ciclos" for v in valores], title=titulo,
                 axis=alt.Axis(labelAngle=0, grid=False, ticks=False))


def etiqueta(w: int) -> str:
    return f"s{w}" if w <= 16 else "entre ciclos"


# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Universidad Qhapaq Ñan")
    st.caption(f"3 sedes · 8 carreras · {VIG.periodo} en curso, semana {SEM} · universidad y datos ficticios")
    sedes = st.multiselect("Sede", sorted(LISTA.sede.unique()), placeholder="Todas")
    carreras = st.multiselect("Carrera", sorted(LISTA.carrera.unique()), placeholder="Todas")
    n_lista = st.slider("Llamadas esta semana", 25, 300, CAPACIDAD, step=25,
                        help="Capacidad de tutoría. La evaluación se hizo con 100 por semana.")
    st.subheader("Modelo vigente")
    st.markdown(
        f'<div class="nota">LightGBM + calibración isotónica<br>entrenado con <b>{VIG.entrenamiento.split(", ")[0]}</b>'
        f' a <b>{VIG.entrenamiento.split(", ")[-1]}</b><br>calibrado con <b>{VIG.calibracion}</b><br>'
        f'<b>{VIG.filas_entrenamiento:,}</b> filas alumno-semana</div>', unsafe_allow_html=True)

filtro = pd.Series(True, index=LISTA.index)
if sedes:
    filtro &= LISTA.sede.isin(sedes)
if carreras:
    filtro &= LISTA.carrera.isin(carreras)
lista = LISTA[filtro]
aus = AUSENTES[(AUSENTES.sede.isin(sedes) | (not sedes)) & (AUSENTES.carrera.isin(carreras) | (not carreras))]

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> desercion</p>', unsafe_allow_html=True)
st.caption("Riesgo de no volver el próximo ciclo, alumno por alumno y semana por semana, con las razones en texto "
           "para tutoría. Las cifras de evaluación salen de un semestre que el modelo no vio.")
st.markdown(f'<div class="estado"><b>●</b> duckdb · {DB.name} · {VIG.periodo} · datos al cierre de la semana {SEM} · '
            f'prueba {PART.prueba} · {CAPACIDAD} llamadas por semana</div>', unsafe_allow_html=True)
st.write("")

tab_lista, tab_alumno, tab_eval, tab_superv = st.tabs([
    ":material/list_alt: Lista de la semana", ":material/person_search: Alumno",
    ":material/fact_check: Evaluación", ":material/timeline: Supervivencia",
])

# ----------------------------------------------------------------- lista

with tab_lista:
    top = lista.head(n_lista)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Activos", f"{len(lista):,}", help="Asistieron o entregaron algo en la semana.")
    m2.metric("Riesgo esperado", f"{lista.riesgo.sum():,.0f}",
              help="Suma de las probabilidades: cuántos de los activos se esperaría que no vuelvan.")
    m3.metric(f"En la lista ({len(top)})", f"{top.riesgo.sum():,.0f}",
              f"{top.riesgo.sum() / lista.riesgo.sum():.0%} del riesgo", delta_color="off", delta_arrow="off",
              help="Desertores esperados entre los que se llamará esta semana.")
    m4.metric("Marcados por la regla", f"{int(lista.regla.sum()):,}", f"{lista.regla.mean():.0%} de activos",
              delta_color="off", delta_arrow="off", help="Asistencia < 70%, evaluación desaprobada o 2+ cuotas vencidas.")
    m5.metric("Ausentes toda la semana", f"{len(aus):,}", "van primero", delta_color="off", delta_arrow="off",
              help="Matriculados sin asistencia ni entregas en la semana. No pasan por el modelo.")

    st.markdown(f"#### Lista de contacto · semana {SEM + 1}")
    vista = top.assign(cambio=(top.riesgo - top.riesgo_semana_anterior) * 100, riesgo_pct=top.riesgo * 100,
                       asistencia_pct=top.asistencia_acum * 100,
                       parcial=top.nota_parcial.map(lambda v: "NSP" if pd.isna(v) else f"{v:.1f}"),
                       razones=top.razon_1 + " · " + top.razon_2 + np.where(top.razon_3 != "", " · " + top.razon_3, ""))
    st.dataframe(
        vista[["puesto", "codigo", "sede", "carrera", "ciclo", "riesgo_pct", "cambio", "asistencia_pct", "parcial",
               "cuotas_vencidas", "razones"]],
        hide_index=True, width="stretch", height=430,
        column_config={
            "puesto": st.column_config.NumberColumn("#", width=40),
            "codigo": "Código", "sede": "Sede", "carrera": "Carrera", "ciclo": st.column_config.NumberColumn("Ciclo", width=50),
            "riesgo_pct": st.column_config.ProgressColumn("Riesgo", format="%.0f%%", min_value=0, max_value=100, width=110),
            "cambio": st.column_config.NumberColumn("vs s ant.", format="%+.0f pts", width=80),
            "asistencia_pct": st.column_config.NumberColumn("Asistencia", format="%.0f%%", width=85),
            "parcial": st.column_config.TextColumn("Parcial", width=65),
            "cuotas_vencidas": st.column_config.NumberColumn("Cuotas venc.", width=85),
            "razones": st.column_config.TextColumn("Por qué está en la lista", width="large"),
        })
    st.download_button("Descargar lista (CSV)", vista.drop(columns=["id_alumno", "puntaje", "riesgo_pct", "asistencia_pct"]).to_csv(index=False).encode("utf-8"),
                       f"lista_{VIG.periodo}_s{SEM}.csv", "text/csv", icon=":material/download:")

    st.markdown(f"#### No asistieron en toda la semana {SEM}")
    st.caption("Siguen matriculados pero no aparecieron ni entregaron nada. No hace falta un modelo: se llaman antes "
               "que la lista, empezando por quienes recién faltan.")
    st.dataframe(aus.head(200).assign(asistencia=aus.asistencia_acum * 100), hide_index=True, width="stretch", height=230, column_config={
        "id_alumno": None, "codigo": "Código", "sede": "Sede", "carrera": "Carrera", "ciclo": "Ciclo",
        "semanas_sin_asistir": "Semanas sin asistir",
        "asistencia_acum": st.column_config.NumberColumn("Asistencia acumulada", format="percent"),
        "cuotas_vencidas": "Cuotas vencidas"} | {"asistencia_acum": None, "asistencia": st.column_config.NumberColumn(
            "Asistencia acumulada", format="%.0f%%")})

# ----------------------------------------------------------------- alumno

with tab_alumno:
    opciones = lista.head(300)
    if opciones.empty:
        st.info("No hay alumnos con esos filtros.", icon=":material/filter_alt_off:")
    else:
        cod = st.selectbox("Alumno (los 300 de mayor riesgo)", opciones.codigo,
                           format_func=lambda c: f"#{int(opciones.set_index('codigo').puesto[c])} · {c}")
        fila = opciones.set_index("codigo").loc[cod]
        ida = int(fila.id_alumno)
        ficha = consultar(DB, "SELECT * FROM alumnos WHERE id_alumno = ?", [ida]).iloc[0]
        mat = consultar(DB, "SELECT * FROM matriculas WHERE id_alumno = ? AND periodo = ?", [ida, VIG.periodo]).iloc[0]

        c1, c2 = st.columns([1, 2.2])
        with c1:
            st.metric("Riesgo", f"{fila.riesgo:.0%}",
                      f"{(fila.riesgo - fila.riesgo_semana_anterior) * 100:+.0f} pts vs semana {SEM - 1}"
                      if pd.notna(fila.riesgo_semana_anterior) else None, delta_color="inverse")
            beca = f"beca {mat.beca_pct:.0f}%" if mat.beca_pct else "sin beca"
            st.markdown(
                f'<div class="ficha"><b>{ficha.carrera}</b> · ciclo {mat.ciclo}<br>{ficha.sede} · {ficha.modalidad}<br>'
                f'ingresó en {ficha.periodo_ingreso} · {"trabaja" if ficha.trabaja else "no trabaja"} · {beca}<br>'
                f'promedio anterior <b>{mat.promedio_anterior:.1f}</b> · {mat.desaprobados_acumulados} cursos '
                f'desaprobados<br>{ficha.tiempo_traslado_min} min de traslado · escala {ficha.escala_pension}</div>'
                if pd.notna(mat.promedio_anterior) else
                f'<div class="ficha"><b>{ficha.carrera}</b> · primer ciclo<br>{ficha.sede} · {ficha.modalidad}<br>'
                f'{"trabaja" if ficha.trabaja else "no trabaja"} · {beca} · puntaje de ingreso {ficha.puntaje_ingreso}<br>'
                f'{ficha.tiempo_traslado_min} min de traslado · escala {ficha.escala_pension}</div>',
                unsafe_allow_html=True)
        with c2:
            hist = consultar(RES, "SELECT semana, riesgo, regla FROM riesgo_actual WHERE id_alumno = ? ORDER BY semana",
                             [ida])
            asis = consultar(DB, """SELECT semana, asistidas / sesiones AS asistencia FROM asistencia
                                    WHERE id_alumno = ? AND periodo = ? ORDER BY semana""", [ida, VIG.periodo])
            hist["etiqueta"] = hist.semana.map(etiqueta)
            asis["etiqueta"] = asis.semana.map(etiqueta)
            semanas = list(range(1, SEM + 1))
            linea = alt.Chart(hist).mark_line(color=ACENTO, strokeWidth=2.4, point=alt.OverlayMarkDef(size=55)).encode(
                x=eje_semana(semanas), y=alt.Y("riesgo:Q", title="riesgo", axis=alt.Axis(format="%"),
                                               scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("etiqueta:N", title="semana"), alt.Tooltip("riesgo:Q", format=".1%")])
            barras = alt.Chart(asis).mark_bar(color=GRIS_OSCURO, opacity=0.7, cornerRadiusEnd=2).encode(
                x=eje_semana(semanas), y=alt.Y("asistencia:Q", title="asistencia de la semana",
                                               axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
                tooltip=[alt.Tooltip("etiqueta:N", title="semana"), alt.Tooltip("asistencia:Q", format=".0%")])
            st.altair_chart(alt.layer(barras, linea).resolve_scale(y="independent").properties(height=250),
                            width="stretch")
            st.caption("Línea: riesgo al cierre de cada semana. Barras: asistencia de esa semana.")

        st.markdown("#### Qué empuja el riesgo esta semana")
        sh = consultar(RES, "SELECT variable, descripcion, shap FROM shap_actual WHERE id_alumno = ?", [ida])
        sh = sh.reindex(sh.shap.abs().sort_values(ascending=False).index).head(10)
        sh["sentido"] = np.where(sh.shap > 0, "sube el riesgo", "lo baja")
        graf = alt.Chart(sh).mark_bar(cornerRadiusEnd=3, height=16).encode(
            y=alt.Y("descripcion:N", sort=list(sh.descripcion), title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X("shap:Q", title="contribución SHAP (log-odds)"),
            color=alt.Color("sentido:N", scale=alt.Scale(domain=["sube el riesgo", "lo baja"], range=[ACENTO, GRIS_OSCURO]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["variable", "descripcion", alt.Tooltip("shap:Q", format="+.3f")])
        regla = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#2A3542").encode(x="x:Q")
        st.altair_chart((graf + regla).properties(height=330), width="stretch")

# ----------------------------------------------------------------- evaluación

with tab_eval:
    met = tabla("metricas_semana")
    cap = tabla("capacidad")
    cap_k = cap[cap.capacidad == CAPACIDAD].set_index("politica")
    ece = tabla("ece").set_index("modelo").ece
    m_l = met[met.modelo == "LightGBM"].set_index("semana")
    m_r = met[met.modelo == "Logística"].set_index("semana")

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Desertores alcanzados", f"{cap_k.loc['modelo', 'alcanzados_pct']:.1%}",
              f"{(cap_k.loc['modelo', 'alcanzados_pct'] - cap_k.loc['regla_actual', 'alcanzados_pct']) * 100:+.1f} pp",
              delta_description="vs regla actual",
              help=f"Desertores de {PART.prueba} llamados mientras todavía iban a clases, con {CAPACIDAD} llamadas por semana.")
    e2.metric("Precisión de la lista", f"{cap_k.loc['modelo', 'precision']:.1%}",
              f"{(cap_k.loc['modelo', 'precision'] - cap_k.loc['regla_actual', 'precision']) * 100:+.1f} pp",
              delta_description="vs regla actual", help="De los llamados, cuántos no volvieron.")
    e3.metric("AUC-PR semana 4", f"{m_l.loc[4, 'auc_pr']:.3f}", f"{m_l.loc[4, 'auc_pr'] - m_r.loc[4, 'auc_pr']:+.3f}",
              delta_description="vs logística", help=f"Deserción base esa semana: {m_l.loc[4, 'tasa']:.1%}.")
    e4.metric("ECE", f"{ece['LightGBM calibrado']:.4f}", "error de calibración", delta_color="off", delta_arrow="off",
              help="Diferencia media entre el riesgo predicho y la tasa observada, por decil.")

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Desertores alcanzados según la capacidad de tutoría")
        cap["politica_n"] = cap.politica.map(POLITICAS)
        g = alt.Chart(cap).mark_line(strokeWidth=2.2, point=alt.OverlayMarkDef(size=45)).encode(
            x=alt.X("capacidad:Q", title="llamadas por semana", scale=alt.Scale(zero=False)),
            y=alt.Y("alcanzados_pct:Q", title="desertores alcanzados", axis=alt.Axis(format="%"),
                    scale=alt.Scale(zero=False)),
            color=alt.Color("politica_n:N", sort=list(POLITICAS.values()),
                            scale=alt.Scale(domain=list(POLITICAS.values()), range=COLORES_POL),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["politica_n", "capacidad", alt.Tooltip("alcanzados_pct:Q", format=".1%"),
                     alt.Tooltip("precision:Q", format=".1%"), "contactos"])
        st.altair_chart(g.properties(height=300), width="stretch")
    with c2:
        st.markdown("#### AUC-PR por semana del ciclo")
        mm = met.copy()
        mm["etiqueta"] = mm.semana.map(etiqueta)
        base_t = mm[mm.modelo == "LightGBM"].assign(modelo="Deserción base", auc_pr=lambda d: d.tasa)
        mm = pd.concat([mm, base_t])
        g = alt.Chart(mm).mark_line(strokeWidth=2.2, point=alt.OverlayMarkDef(size=40)).encode(
            x=eje_semana(sorted(met.semana.unique())),
            y=alt.Y("auc_pr:Q", title="AUC-PR", scale=alt.Scale(zero=False)),
            color=alt.Color("modelo:N", scale=alt.Scale(domain=["LightGBM", "Logística", "Deserción base"],
                                                         range=[ACENTO, "#A78BFA", GRIS_OSCURO]),
                            legend=alt.Legend(orient="bottom", title=None)),
            strokeDash=alt.condition(alt.datum.modelo == "Deserción base", alt.value([4, 3]), alt.value([1, 0])),
            tooltip=["modelo", "etiqueta", alt.Tooltip("auc_pr:Q", format=".3f")])
        st.altair_chart(g.properties(height=300), width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("#### Calibración en la prueba")
        cal = tabla("calibracion")
        cal = cal[cal.modelo == "LightGBM calibrado"]
        pts = alt.Chart(cal).mark_line(color=ACENTO, strokeWidth=2, point=alt.OverlayMarkDef(size=60)).encode(
            x=alt.X("p_media:Q", title="riesgo predicho (promedio del decil)", axis=alt.Axis(format="%")),
            y=alt.Y("tasa_obs:Q", title="deserción observada", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("p_media:Q", format=".1%"), alt.Tooltip("tasa_obs:Q", format=".1%"), "n"])
        diag = alt.Chart(pd.DataFrame({"x": [0, 0.55], "y": [0, 0.55]})).mark_line(
            color=GRIS_OSCURO, strokeDash=[4, 3]).encode(x="x:Q", y="y:Q")
        st.altair_chart((diag + pts).properties(height=370), width="stretch")
    with c4:
        st.markdown("#### Qué pesa en el modelo (SHAP medio)")
        imp = tabla("importancia").head(14)
        g = alt.Chart(imp).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("variable:N", sort="-x", title=None, scale=alt.Scale(paddingInner=0.3),
                    axis=alt.Axis(labelLimit=220, labelOverlap=False)),
            x=alt.X("shap_medio:Q", title="|SHAP| medio (log-odds)"),
            color=alt.Color("tipo:N", scale=alt.Scale(domain=["de la semana", "de la ficha"], range=[ACENTO, GRIS_OSCURO]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["variable", "tipo", alt.Tooltip("shap_medio:Q", format=".3f")])
        st.altair_chart(g.properties(height=370), width="stretch")

    if "alcance_causas" in tablas(RES):
        st.markdown("#### A quién no llega la lista")
        st.caption("La causa de cada deserción solo existe porque los datos son simulados; el modelo nunca la ve.")
        cz = tabla("alcance_causas")
        cz = (cz.pivot(index=["causa", "desertores"], columns="politica", values="alcanzados_pct") * 100).reset_index()
        st.dataframe(cz[["causa", "desertores", "modelo", "regla_ordenada", "regla_actual"]].sort_values("desertores", ascending=False),
                     hide_index=True, width="stretch", column_config={
                         "causa": "Causa", "desertores": "Desertores",
                         "modelo": st.column_config.NumberColumn("LightGBM", format="%.0f%%"),
                         "regla_ordenada": st.column_config.NumberColumn("Regla ordenada", format="%.0f%%"),
                         "regla_actual": st.column_config.NumberColumn("Regla actual", format="%.0f%%")})

# ----------------------------------------------------------------- supervivencia

with tab_superv:
    km = tabla("km")
    lr = tabla("logrank").set_index("grupo").p_logrank
    haz = tabla("riesgo_semanal")
    cox = tabla("cox")
    nombres = {"ciclo": "Ciclo", "modalidad": "Modalidad", "trabaja": "Trabaja", "beca": "Beca"}
    grupo = st.segmented_control("Comparar por", list(nombres), default="ciclo", format_func=nombres.get)
    grupo = grupo or "ciclo"
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.markdown("#### Permanencia durante el ciclo (Kaplan-Meier)")
        d = km[km.grupo == grupo].copy()
        d["etiqueta"] = d.semana.map(lambda w: "inicio" if w == 0 else etiqueta(w))
        orden = ["inicio"] + [etiqueta(w) for w in range(1, 18)]
        x = alt.X("etiqueta:O", sort=orden, title=None, axis=alt.Axis(labelAngle=0, grid=False, ticks=False,
                                                                       values=["inicio", "s4", "s8", "s12", "s16", "entre ciclos"]))
        colores = alt.Scale(range=[ACENTO, AMBAR, "#A78BFA"])
        banda = alt.Chart(d).mark_area(opacity=0.15, interpolate="step-after").encode(
            x=x, y="ic_inf:Q", y2="ic_sup:Q", color=alt.Color("valor:N", scale=colores,
                                                         legend=alt.Legend(orient="bottom", title=None, symbolOpacity=1)))
        linea = alt.Chart(d).mark_line(strokeWidth=2.2, interpolate="step-after").encode(
            x=x, y=alt.Y("permanencia:Q", title="siguen en la universidad", axis=alt.Axis(format="%"),
                         scale=alt.Scale(zero=False)),
            color=alt.Color("valor:N", scale=colores, legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["valor", "etiqueta", alt.Tooltip("permanencia:Q", format=".1%"), "alumnos"])
        st.altair_chart((banda + linea).properties(height=310), width="stretch")
        p_txt = "< 1e-300" if lr[grupo] == 0 else f"= {lr[grupo]:.1e}"
        st.caption(f"Log-rank p {p_txt}. Semestres {PART.entrenamiento.split(', ')[0]} a {PART.prueba}, "
                   "sin egresados.")
    with c2:
        st.markdown("#### Riesgo de abandono por semana")
        haz["etiqueta"] = haz.semana.map(etiqueta)
        haz["tipo"] = np.where(haz.semana == 17, "entre ciclos", "durante el ciclo")
        g = alt.Chart(haz).mark_bar(cornerRadiusEnd=2).encode(
            x=eje_semana(list(range(1, 18))),
            y=alt.Y("riesgo:Q", title="dejaron de ir / seguían yendo", axis=alt.Axis(format=".1%")),
            color=alt.Color("tipo:N", scale=alt.Scale(domain=["durante el ciclo", "entre ciclos"], range=[ACENTO, GRIS_OSCURO]),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["etiqueta", "abandonos", "en_riesgo", alt.Tooltip("riesgo:Q", format=".2%")])
        st.altair_chart(g.properties(height=310), width="stretch")
        tot = haz.abandonos.sum()
        st.caption(f"{haz.loc[haz.semana == 17, 'abandonos'].iloc[0] / tot:.0%} de las deserciones ocurre entre ciclos: "
                   "terminan el semestre y no se matriculan.")

    st.markdown("#### Cox con lo que se sabe en la semana 4")
    cres = tabla("cox_resumen").iloc[0]
    cox["sig"] = np.where(cox.p < 0.05, "p < 0.05", "no significativo")
    base = alt.Chart(cox).encode(y=alt.Y("descripcion:N", sort=list(cox.descripcion), title=None,
                                         axis=alt.Axis(labelLimit=260, labelOverlap=False)))
    ic = base.mark_rule(color=GRIS, strokeWidth=1.6).encode(x=alt.X("ic_inf:Q", scale=alt.Scale(type="log", domain=[0.5, 6]),
                                                                    title="hazard ratio (escala log)"), x2="ic_sup:Q")
    pt = base.mark_point(filled=True, size=90).encode(
        x=alt.X("hr:Q", scale=alt.Scale(type="log", domain=[0.5, 6])), color=alt.Color("sig:N", scale=alt.Scale(domain=["p < 0.05", "no significativo"], range=[ACENTO, GRIS_OSCURO]),
                                  legend=alt.Legend(orient="top", title=None)),
        tooltip=["descripcion", alt.Tooltip("hr:Q", format=".2f"), alt.Tooltip("ic_inf:Q", format=".2f"),
                 alt.Tooltip("ic_sup:Q", format=".2f"), alt.Tooltip("prevalencia:Q", format=".0%")])
    uno = alt.Chart(pd.DataFrame({"x": [1]})).mark_rule(color="#2A3542", strokeDash=[4, 3]).encode(
        x=alt.X("x:Q", scale=alt.Scale(type="log", domain=[0.5, 6])))
    st.altair_chart((uno + ic + pt).properties(height=330), width="stretch")
    st.caption(f"{int(cres.alumnos):,} alumno-semestres que seguían yendo en la semana 4 · concordancia "
               f"{cres.concordancia:.3f}. Con la asistencia y la PC1 en el modelo, beca y modalidad ya no agregan.")
