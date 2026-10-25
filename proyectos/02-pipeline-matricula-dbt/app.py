"""
Tablero de matrícula sobre los marts de dbt.

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from matricula.consultas import Consultas, Kpis, periodo_anterior  # noqa: E402
from matricula.rutas import leer_manifiesto, ruta_db  # noqa: E402

st.set_page_config(page_title="matricula · Universidad Mirasol", page_icon=":material/school:", layout="wide")

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
.estado b.aviso { color: #FBBF24; }
.nota { font-size: .85rem; color: #9AA7B4; }
.nota b { color: #D6DEE6; font-family: 'JetBrains Mono', monospace; font-weight: 600; }
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO = "#22D3EE"
GRISES = ["#7D8B99", "#46535F", "#2C3640"]
AMBAR = "#FBBF24"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def tema_oscuro():
    return {"config": {
        "background": "transparent",
        "view": {"stroke": "transparent"},
        "font": "Inter",
        "axis": {"labelColor": "#9AA7B4", "titleColor": "#7D8B99", "gridColor": "#1A222C",
                 "domainColor": "#2A3542", "tickColor": "#2A3542", "labelFontSize": 11,
                 "titleFontSize": 11, "titleFontWeight": 500},
        "legend": {"labelColor": "#9AA7B4", "titleColor": "#7D8B99", "labelFontSize": 11, "titleFontSize": 11},
        "title": {"color": "#D6DEE6", "fontSize": 13, "fontWeight": 600, "anchor": "start"},
    }}


alt.themes.register("consola", tema_oscuro)
alt.themes.enable("consola")


def fecha_corta(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]}"


# Conexión de solo lectura que se abre y se cierra en cada ejecución del script:
# si quedara abierta, DuckDB bloquearía el archivo y el próximo dbt build fallaría.
try:
    c = Consultas(ruta_db())
except FileNotFoundError as e:
    st.error(str(e), icon=":material/database:")
    st.code("python -m matricula generar\npython -m matricula build", language="bash")
    st.stop()

PERIODOS = c.periodos()
try:
    MANIFIESTO = leer_manifiesto()
except FileNotFoundError:
    MANIFIESTO = {"corte": "-", "anomalias": {}}

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Universidad Mirasol")
    st.caption("3 sedes · 8 carreras · 2024-1 a 2026-2 · universidad y datos ficticios")
    periodo = st.selectbox("Periodo", PERIODOS[::-1], index=0)
    st.caption(f"Se compara contra {periodo_anterior(periodo, 2)}, el mismo semestre del año anterior.")

    corridas = c.corridas(1)
    if not corridas.empty:
        u = corridas.iloc[0]
        st.subheader("Último build")
        st.markdown(
            f'<div class="nota">{pd.Timestamp(u.fecha):%d/%m/%Y %H:%M}<br>'
            f'<b>{u.modelos}</b> modelos · <b>{u.tests_ok}</b> tests OK · '
            f'<b>{u.tests_warn}</b> aviso · <b>{u.tests_error}</b> fallas<br>{u.segundos:.1f} s</div>',
            unsafe_allow_html=True,
        )

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> matricula</p>', unsafe_allow_html=True)
st.caption("Exports del sistema académico → dbt (staging, intermedio, marts) → DuckDB. "
           "Todo lo que se ve aquí sale de los marts y pasó los tests del build.")
ultimo = c.corridas(1)
ok = not ultimo.empty and bool(ultimo.iloc[0].exito)
marca = '<b>●</b>' if ok else '<b class="aviso">●</b>'
st.markdown(
    f'<div class="estado">{marca} duckdb · {ruta_db().name} · corte {MANIFIESTO["corte"]} · '
    f'dbt build {"OK" if ok else "sin registro"}</div>',
    unsafe_allow_html=True,
)
st.write("")

k = c.kpis(periodo)


def delta(actual, anterior):
    v = Kpis.variacion(actual, anterior)
    return None if v is None else f"{v:+.1%}"


m1, m2, m3, m4, m5 = st.columns(5)
previo = f"vs {periodo_anterior(periodo, 2)}"
m1.metric("Matriculados", f"{k.matriculados:,}", delta(k.matriculados, k.matriculados_anio_anterior),
          delta_description=previo)
m2.metric("Ingresantes", f"{k.ingresantes:,}", delta(k.ingresantes, k.ingresantes_anio_anterior),
          delta_description=previo)
m3.metric("Extemporánea", f"{k.pct_extemporanea:.1%}",
          help="Alumnos que se matricularon después del inicio de clases.")
m4.metric("Con deuda vencida", f"{k.pct_con_deuda:.1%}",
          help="Alumnos con al menos una pensión vencida y no pagada al cierre del ciclo (o al corte).")
m5.metric("Baja demanda", f"{k.secciones_baja_demanda} / {k.secciones}",
          help="Secciones presenciales con menos de 40% de ocupación al cierre de la extemporánea.")

st.write("")
tab_avance, tab_secciones, tab_retencion, tab_cursos, tab_calidad = st.tabs([
    ":material/trending_up: Avance de matrícula", ":material/meeting_room: Secciones",
    ":material/group: Retención", ":material/filter_alt: Cursos filtro", ":material/rule: Calidad de datos",
])

# ----------------------------------------------------------------- avance

with tab_avance:
    comparar = [p for p in (periodo, periodo_anterior(periodo, 2), periodo_anterior(periodo, 4)) if p in PERIODOS]
    av = c.avance(comparar)
    av["fecha_txt"] = av["fecha"].map(fecha_corta)
    inicio_clases = int(av.loc[av["es_extemporanea"], "dia"].min())

    col_graf, col_lado = st.columns([3, 1.1])
    with col_graf:
        st.markdown("#### Alumnos matriculados por día desde la apertura")
        colores = alt.Scale(domain=comparar, range=[ACENTO] + GRISES[: len(comparar) - 1])
        base = alt.Chart(av).encode(
            x=alt.X("dia:Q", title="día desde la apertura de la matrícula",
                    scale=alt.Scale(domain=[0, int(av["dia"].max())], nice=False),
                    axis=alt.Axis(values=list(range(0, 28, 3)))),
            y=alt.Y("matriculados_acumulados:Q", title="matriculados acumulados",
                    scale=alt.Scale(zero=False), axis=alt.Axis(format=",d")),
            color=alt.Color("periodo:N", scale=colores, legend=alt.Legend(orient="top-left", title=None)),
            tooltip=[alt.Tooltip("periodo:N"), alt.Tooltip("dia:Q", title="día"),
                     alt.Tooltip("fecha_txt:N", title="fecha"),
                     alt.Tooltip("matriculados_acumulados:Q", title="acumulados", format=",d"),
                     alt.Tooltip("matriculados_dia:Q", title="ese día", format=",d")],
        )
        lineas = base.mark_line(strokeWidth=2.4, interpolate="monotone")
        regla = alt.Chart(pd.DataFrame({"dia": [inicio_clases]})).mark_rule(
            color="#46535F", strokeDash=[4, 4]).encode(x="dia:Q")
        etiqueta = alt.Chart(pd.DataFrame({"dia": [inicio_clases], "t": ["inicio de clases"]})
                             ).mark_text(align="left", dx=6, color="#7D8B99", fontSize=11
                                         ).encode(x="dia:Q", y=alt.value(230), text="t:N")
        st.altair_chart((regla + etiqueta + lineas).properties(height=340), width="stretch")

    with col_lado:
        st.markdown("#### Turnos por orden de mérito")
        deuda = c.dia_matricula_por_deuda()
        for f in deuda.itertuples():
            st.metric(f.grupo, f"día {f.dia_promedio:.1f}",
                      f"{f.pct_extemporanea:.1%} extemporánea", delta_color="off", delta_arrow="off")
        st.caption("Los mejores promedios se matriculan primero. Quien arrastra pensiones vencidas "
                   "no puede matricularse hasta pagar, y termina en los últimos días o en la extemporánea, "
                   "cuando ya no quedan vacantes en la mañana.")

    st.markdown("#### Matriculados por periodo")
    por = c.matricula_por_periodo().melt(id_vars="periodo", value_vars=["continuadores", "ingresantes"],
                                         var_name="tipo", value_name="alumnos")
    barras = alt.Chart(por).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        x=alt.X("periodo:O", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("alumnos:Q", title="alumnos", axis=alt.Axis(format=",d")),
        color=alt.Color("tipo:N", scale=alt.Scale(domain=["continuadores", "ingresantes"], range=["#2C3640", ACENTO]),
                        legend=alt.Legend(orient="top", title=None)),
        order=alt.Order("tipo:N", sort="ascending"),
        tooltip=["periodo", "tipo", alt.Tooltip("alumnos:Q", format=",d")],
    )
    st.altair_chart(barras.properties(height=240), width="stretch")

# ----------------------------------------------------------------- secciones

with tab_secciones:
    col_a, col_b = st.columns([1.1, 1])
    with col_a:
        st.markdown(f"#### Ocupación por sede y turno · {periodo}")
        oc = c.ocupacion_sede_turno(periodo)
        oc["etiqueta"] = oc["ocupacion"].map(lambda x: f"{x:.0%}")
        orden_sede = ["Lima Norte", "Lima Centro", "Arequipa", "Virtual"]
        orden_turno = ["Mañana", "Tarde", "Noche"]
        celdas = alt.Chart(oc).encode(
            x=alt.X("turno:N", sort=orden_turno, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
            y=alt.Y("sede:N", sort=orden_sede, title=None),
        )
        mapa = celdas.mark_rect(cornerRadius=3, stroke="#0B0F14", strokeWidth=3).encode(
            color=alt.Color("ocupacion:Q", scale=alt.Scale(domain=[0.3, 1], range=["#12202A", ACENTO]),
                            legend=None),
            tooltip=["sede", "turno", "secciones", alt.Tooltip("ocupacion:Q", format=".1%"),
                     "baja_demanda", "llenas"],
        )
        texto = celdas.mark_text(font="JetBrains Mono", fontSize=13).encode(
            text="etiqueta:N",
            color=alt.condition("datum.ocupacion > 0.75", alt.value("#0B0F14"), alt.value("#D6DEE6")),
        )
        st.altair_chart((mapa + texto).properties(height=260), width="stretch")
        st.caption("Inscritos al cierre de la extemporánea / vacantes. Las secciones virtuales "
                   "son de 60 vacantes y se dictan en la noche.")

    with col_b:
        st.markdown("#### Presencial vs virtual")
        mod = c.ocupacion_por_modalidad()
        lineas = alt.Chart(mod).mark_line(strokeWidth=2.4, point=alt.OverlayMarkDef(size=50)).encode(
            x=alt.X("periodo:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("ocupacion:Q", title="ocupación", scale=alt.Scale(zero=False), axis=alt.Axis(format="%")),
            color=alt.Color("modalidad:N", scale=alt.Scale(domain=["Virtual", "Presencial"], range=[ACENTO, GRISES[0]]),
                            legend=alt.Legend(orient="bottom-left", title=None)),
            tooltip=["periodo", "modalidad", "secciones", alt.Tooltip("ocupacion:Q", format=".1%")],
        )
        st.altair_chart(lineas.properties(height=260), width="stretch")

    baja = c.secciones_baja_demanda(periodo)
    st.markdown(f"#### Secciones presenciales con menos de 40% de ocupación · {len(baja)}")
    st.dataframe(
        baja, hide_index=True, width="stretch", height=300,
        column_config={
            "seccion_id": st.column_config.TextColumn("sección"),
            "inscritos_cierre": st.column_config.NumberColumn("inscritos"),
            "ocupacion": st.column_config.ProgressColumn("ocupación", format="percent", min_value=0, max_value=1),
        },
    )

# ----------------------------------------------------------------- retención

with tab_retencion:
    st.markdown("#### Retención por cohorte")
    ret = c.retencion()
    ret["k"] = ret["periodos_desde_ingreso"].map(lambda x: f"+{x}")
    ret["etiqueta"] = ret["tasa_retencion"].map(lambda x: f"{x:.0%}")
    orden_k = [f"+{i}" for i in range(int(ret["periodos_desde_ingreso"].max()) + 1)]
    celdas = alt.Chart(ret).encode(
        x=alt.X("k:N", sort=orden_k, title="periodos desde el ingreso", axis=alt.Axis(labelAngle=0, orient="top")),
        y=alt.Y("cohorte:N", title=None),
    )
    mapa = celdas.mark_rect(cornerRadius=3, stroke="#0B0F14", strokeWidth=3).encode(
        color=alt.Color("tasa_retencion:Q", scale=alt.Scale(domain=[0.55, 1], range=["#12202A", ACENTO]), legend=None),
        tooltip=["cohorte", alt.Tooltip("periodos_desde_ingreso:Q", title="periodos"),
                 alt.Tooltip("ingresantes_matriculados:Q", title="base", format=",d"),
                 alt.Tooltip("matriculados:Q", format=",d"), alt.Tooltip("tasa_retencion:Q", format=".1%")],
    )
    texto = celdas.mark_text(font="JetBrains Mono", fontSize=12).encode(
        text="etiqueta:N",
        color=alt.condition("datum.tasa_retencion > 0.85", alt.value("#0B0F14"), alt.value("#D6DEE6")),
    )
    st.altair_chart((mapa + texto).properties(height=240), width="stretch")
    st.caption("Base: ingresantes que se matricularon en su primer periodo. Un admitido que nunca "
               "se matriculó es un problema de admisión, no de retención, y no entra aquí.")

    col_d, col_p = st.columns(2)

    def barras_continuidad(df: pd.DataFrame, orden: list[str], titulo: str):
        df = df.assign(etiqueta=df["tasa_continua"].map(lambda x: f"{x:.0%}"))
        b = alt.Chart(df).encode(
            y=alt.Y("segmento:N", sort=orden, title=None),
            x=alt.X("tasa_continua:Q", title="se matricula el ciclo siguiente",
                    scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            tooltip=["segmento", alt.Tooltip("alumnos:Q", format=",d"), alt.Tooltip("tasa_continua:Q", format=".1%")],
        )
        g = b.mark_bar(color=ACENTO, cornerRadiusEnd=3, height=22) + b.mark_text(
            align="left", dx=6, font="JetBrains Mono", color="#D6DEE6").encode(text="etiqueta:N")
        st.markdown(f"#### {titulo}")
        st.altair_chart(g.properties(height=200), width="stretch")

    with col_d:
        barras_continuidad(c.continuidad("deuda"), ["0 cuotas", "1 cuota", "2 cuotas", "3 o más"],
                           "Continuidad según cuotas vencidas al cierre")
    with col_p:
        barras_continuidad(c.continuidad("promedio"), ["menos de 8", "8 a 10.9", "11 a 13.9", "14 o más"],
                           "Continuidad según promedio ponderado del ciclo")

# ----------------------------------------------------------------- cursos filtro

with tab_cursos:
    st.markdown("#### Cursos donde más alumnos no aprueban · periodos cerrados")
    cf = c.cursos_filtro(n=12)
    largo = cf.melt(id_vars=["curso", "inscritos", "tasa_no_aprobacion"],
                    value_vars=["tasa_desaprobacion", "tasa_retiro"], var_name="motivo", value_name="tasa")
    largo["motivo"] = largo["motivo"].map({"tasa_desaprobacion": "desaprobó", "tasa_retiro": "se retiró"})
    orden = list(cf["curso"])
    barras = alt.Chart(largo).mark_bar(height=20).encode(
        y=alt.Y("curso:N", sort=orden, title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X("tasa:Q", stack="zero", title="% de inscritos", axis=alt.Axis(format="%")),
        color=alt.Color("motivo:N", scale=alt.Scale(domain=["desaprobó", "se retiró"], range=[ACENTO, AMBAR]),
                        legend=alt.Legend(orient="top-right", title=None)),
        order=alt.Order("motivo:N", sort="ascending"),
        tooltip=["curso", "motivo", alt.Tooltip("tasa:Q", format=".1%"), alt.Tooltip("inscritos:Q", format=",d")],
    )
    st.altair_chart(barras.properties(height=420), width="stretch")
    st.caption("Solo cursos con al menos 300 inscritos. Retiro + desaprobación sobre el total de inscritos; "
               "un NSP cuenta como desaprobado.")

# ----------------------------------------------------------------- calidad

with tab_calidad:
    st.markdown("#### Qué se limpió en el último export")
    cal = c.calidad()
    cal["inyectados"] = cal["regla_id"].map(MANIFIESTO["anomalias"])
    cal["cuadra"] = cal["registros"] == cal["inyectados"]
    st.dataframe(
        cal[["regla", "tabla", "accion", "registros", "pct", "inyectados", "cuadra"]],
        hide_index=True, width="stretch",
        column_config={
            "accion": "acción",
            "registros": st.column_config.NumberColumn(format="localized"),
            "pct": st.column_config.NumberColumn("% de la tabla", format="percent"),
            "inyectados": st.column_config.NumberColumn("inyectados por el generador", format="localized"),
            "cuadra": st.column_config.CheckboxColumn("cuadra"),
        },
    )
    st.caption("El generador anota cuántos problemas metió en cada export (_anomalias.json). "
               "Si una regla detecta más o menos de lo inyectado, el test de pytest falla.")

    col_t, col_h = st.columns([1.6, 1])
    with col_t:
        st.markdown("#### Tests de la última corrida")
        res = c.resultados_tests()
        if res.empty:
            st.caption("Sin registro. Corre `python -m matricula build`.")
        else:
            st.dataframe(res[["estado", "tipo", "nombre", "filas"]], hide_index=True, width="stretch", height=320,
                         column_config={"estado": st.column_config.TextColumn(width="small"),
                                        "tipo": st.column_config.TextColumn(width="small"),
                                        "nombre": st.column_config.TextColumn(width="large"),
                                        "filas": st.column_config.NumberColumn("filas", width="small")})
    with col_h:
        st.markdown("#### Historial de corridas")
        hist = c.corridas(10)
        if not hist.empty:
            st.dataframe(hist[["fecha", "segundos", "tests_ok", "tests_warn", "tests_error"]],
                         hide_index=True, width="stretch",
                         column_config={"fecha": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                        "tests_ok": "ok", "tests_warn": "aviso", "tests_error": "falla"})

c.cerrar()
