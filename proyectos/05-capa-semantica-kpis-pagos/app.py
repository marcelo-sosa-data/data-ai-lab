"""
Tablero de KPIs de Tinkuy Pay sobre la capa semántica: resumen del mes, explorador de
métricas con su SQL, monitor diario de alertas y explicación de cada anomalía.

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

from kpis import formato as fmt  # noqa: E402
from kpis.calendario import etiqueta_dia, etiqueta_periodo  # noqa: E402
from kpis.capa import CapaSemantica  # noqa: E402
from kpis.compilador import DIALECTOS, Consulta  # noqa: E402
from kpis.explicacion import UMBRAL, dimensiones_por_defecto, explicar_dia, explicar_periodos  # noqa: E402
from kpis.rutas import ruta_db, ruta_resultados, ruta_semantica  # noqa: E402

st.set_page_config(page_title="kpis · Tinkuy Pay", page_icon=":material/monitoring:", layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
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
.lectura { font-family: 'JetBrains Mono', monospace; font-size: .92rem; border-radius: 8px; padding: 12px 16px;
           border: 1px solid #1F2A36; background: #0F151C; margin: .2rem 0 .8rem 0; color: #D6DEE6; }
.lectura .c { color: #22D3EE; font-weight: 600; }
.lectura .r { color: #F87171; font-weight: 600; }
.lectura .v { color: #34D399; font-weight: 600; }
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
    st.error("Faltan los datos o los resultados del monitor.", icon=":material/database:")
    st.code("python -m kpis todo", language="bash")
    st.stop()


@st.cache_resource(show_spinner=False)
def capa() -> CapaSemantica:
    return CapaSemantica.desde_yaml()


@st.cache_resource(show_spinner=False)
def conexion() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB), read_only=True)


CAPA = capa()
DEF = CAPA.definicion


@st.cache_data(show_spinner=False)
def consultar(metricas: tuple, dims: tuple = (), grano=None, desde=None, hasta=None, filtros: tuple = ()):
    q = Consulta(metricas=list(metricas), dimensiones=list(dims), grano=grano, desde=desde, hasta=hasta,
                 filtros={k: list(v) for k, v in filtros})
    return CAPA.consultar(conexion().cursor(), q), CAPA.sql(q)


@st.cache_data(show_spinner=False)
def resultado(nombre: str) -> pd.DataFrame:
    con = duckdb.connect(str(RES), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {nombre}").df()
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def explicacion_dia(metrica: str, fecha, filtros: tuple = (), dims: tuple = ()):
    return explicar_dia(CAPA, conexion().cursor(), metrica, fecha, list(dims) or None, dict(filtros))


@st.cache_data(show_spinner=False)
def explicacion_meses(metrica: str, actual: str, base: str):
    def rango(m):
        i = pd.Timestamp(m)
        return str(i.date()), str((i + pd.offsets.MonthEnd(0)).date())
    return explicar_periodos(CAPA, conexion().cursor(), metrica, rango(actual), rango(base))


SERIE, EVENTOS, EXPL = resultado("serie"), resultado("eventos"), resultado("explicaciones")
EVAL, FALSAS, CORRIDA = resultado("evaluacion"), resultado("falsas"), resultado("corrida").iloc[0]
RANGO = conexion().execute("SELECT MIN(fecha), MAX(fecha), COUNT(*) FROM transacciones").fetchone()
ETIQ = {n: m.etiqueta for n, m in DEF.metricas.items()}


def eje_mensual(fechas: pd.Series) -> tuple[list[str], list[str]]:
    """Etiquetas de día armadas en Python y, para el eje, solo el primer día de cada mes."""
    txt = [f"{etiqueta_dia(d)} {pd.Timestamp(d).year}" for d in fechas]
    valores = [t for t, d in zip(txt, fechas) if pd.Timestamp(d).day == 1]
    return txt, valores


def serie_mensual(df: pd.DataFrame, col: str, formato: str, color=ACENTO, alto=260) -> alt.Chart:
    datos = df.copy()
    datos["mes"] = datos.periodo.map(lambda d: etiqueta_periodo(d, "mes"))
    datos["txt"] = datos[col].map(lambda v: fmt.valor(v, formato))
    base = alt.Chart(datos).encode(
        x=alt.X("mes:O", sort=list(datos.mes), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{col}:Q", title=None, scale=alt.Scale(zero=False, nice=True),
                axis=alt.Axis(format=".1%" if formato.startswith("porcentaje") else "~s")),
        tooltip=[alt.Tooltip("mes:N", title="mes"), alt.Tooltip("txt:N", title=ETIQ.get(col, col))])
    return (base.mark_line(color=color, strokeWidth=2.4) + base.mark_circle(color=color, size=55)
            ).properties(height=alto)


# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Tinkuy Pay")
    st.caption("Pasarela de pagos ficticia para comercios en Lima y provincias · datos sintéticos")
    st.markdown(f'<div class="nota"><b>{RANGO[2]:,}</b> cobros<br>{etiqueta_dia(RANGO[0], True)} a '
                f'{etiqueta_dia(RANGO[1], True)}</div>', unsafe_allow_html=True)
    st.subheader("Capa semántica")
    st.markdown(f'<div class="nota"><b>{len(DEF.metricas)}</b> métricas · <b>{len(DEF.medidas)}</b> medidas · '
                f'<b>{len(DEF.dimensiones())}</b> dimensiones<br>{ruta_semantica().name}</div>',
                unsafe_allow_html=True)
    st.subheader("Último monitor")
    st.markdown(f'<div class="nota">{pd.Timestamp(CORRIDA.fecha):%d/%m/%Y %H:%M} · {CORRIDA.segundos:.1f} s<br>'
                f'<b>{int(CORRIDA.dias)}</b> días evaluados · <b>{len(EVENTOS)}</b> eventos</div>',
                unsafe_allow_html=True)

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> kpis</p>', unsafe_allow_html=True)
st.caption("Métricas definidas una sola vez en YAML y compiladas a SQL. El mismo archivo alimenta este tablero, "
           "la CLI, el monitor diario y la explicación de cada anomalía.")
st.markdown(f'<div class="estado"><b>●</b> duckdb · {DB.name} · solo lectura · semántica: {ruta_semantica().name} · '
            f'dialectos: {", ".join(DIALECTOS)}</div>', unsafe_allow_html=True)
st.write("")

tab_res, tab_exp, tab_mon, tab_expl, tab_cat = st.tabs([
    ":material/dashboard: Resumen", ":material/query_stats: Explorar", ":material/notifications_active: Monitor",
    ":material/troubleshoot: Explicar", ":material/menu_book: Catálogo",
])

# ----------------------------------------------------------------- resumen

with tab_res:
    meses, _ = consultar(("tpv", "transacciones", "tasa_aprobacion", "ticket_promedio", "take_rate",
                          "comercios_activos"), grano="mes")
    ult, prev = meses.iloc[-1], meses.iloc[-2]
    st.markdown(f"#### {etiqueta_periodo(ult.periodo, 'mes')} contra {etiqueta_periodo(prev.periodo, 'mes')}")
    cols = st.columns(3) + st.columns(3)
    for c, m in zip(cols, ["tpv", "transacciones", "tasa_aprobacion", "ticket_promedio", "take_rate",
                           "comercios_activos"]):
        f = DEF.metricas[m].formato
        txt = f"S/ {ult[m] / 1e6:,.2f} M" if f == "soles" else fmt.valor(ult[m], f)
        c.metric(ETIQ[m], txt, fmt.cambio(prev[m], ult[m], f), help=DEF.metricas[m].descripcion or None)
    st.write("")
    izq, der = st.columns(2)
    with izq:
        st.markdown("#### TPV mensual")
        st.altair_chart(serie_mensual(meses, "tpv", "soles"), width="stretch")
    with der:
        st.markdown("#### Ticket promedio")
        st.altair_chart(serie_mensual(meses, "ticket_promedio", "soles_decimal", AMBAR), width="stretch")
    e = explicacion_meses("ticket_promedio", "2026-08-01", "2026-04-01")
    r = e.ranking.set_index("dimension")
    st.markdown(
        f'<div class="lectura">ticket abr → ago 2026: {fmt.valor(e.valor_base, "soles_decimal")} → '
        f'{fmt.valor(e.valor_actual, "soles_decimal")} <span class="r">{fmt.cambio(e.valor_base, e.valor_actual, "soles_decimal")}</span>'
        f' · por rubro: mezcla <span class="c">{fmt.contribucion(r.loc["rubro", "efecto_mezcla"], "soles_decimal")}</span>, '
        f'dentro de cada rubro <span class="c">{fmt.contribucion(r.loc["rubro", "efecto_tasa"], "soles_decimal")}</span>'
        f' · el ticket dentro de cada rubro casi no se movió: cambió quién cobra</div>',
        unsafe_allow_html=True)

# ----------------------------------------------------------------- explorar

with tab_exp:
    c1, c2, c3, c4 = st.columns([2.2, 1.2, 1, 1.6])
    mets = c1.multiselect("Métricas", list(DEF.metricas), default=["tasa_aprobacion"], format_func=ETIQ.get,
                          max_selections=3)
    dim = c2.selectbox("Por", ["(ninguna)"] + DEF.dimensiones(), index=DEF.dimensiones().index("metodo") + 1)
    grano = c3.selectbox("Grano", ["mes", "semana", "dia", "trimestre", "(total)"])
    fechas = c4.date_input("Rango", (pd.Timestamp("2025-10-01").date(), RANGO[1]), min_value=RANGO[0],
                           max_value=RANGO[1], format="DD/MM/YYYY")
    f1, f2, f3 = st.columns(3)
    filtros = {}
    for col, d in zip((f1, f2, f3), ("region", "rubro", "metodo")):
        valores = consultar(("transacciones",), (d,))[0][d].astype(str).tolist()
        sel = col.multiselect(d, valores, placeholder="todos")
        if sel:
            filtros[d] = tuple(sel)
    if not mets:
        st.info("Elige al menos una métrica.", icon=":material/info:")
    else:
        desde, hasta = (fechas[0], fechas[1]) if len(fechas) == 2 else (fechas[0], fechas[0])
        dims = () if dim == "(ninguna)" else (dim,)
        g = None if grano == "(total)" else grano
        df, sql = consultar(tuple(mets), dims, g, str(desde), str(hasta), tuple(sorted(filtros.items())))
        principal = mets[0]
        f = DEF.metricas[principal].formato
        if g and len(df) > 1:
            datos = df.copy()
            datos["x"] = datos.periodo.map(lambda d: etiqueta_periodo(d, g))
            orden = list(dict.fromkeys(datos.x))
            datos["txt"] = datos[principal].map(lambda v: fmt.valor(v, f))
            enc = dict(x=alt.X("x:O", sort=orden, title=None, axis=alt.Axis(
                           labelAngle=0, values=orden[::max(1, len(orden) // 12)])),
                       y=alt.Y(f"{principal}:Q", title=ETIQ[principal], scale=alt.Scale(zero=False, nice=True),
                               axis=alt.Axis(format=".1%" if f.startswith("porcentaje") else "~s")),
                       tooltip=[alt.Tooltip("x:N", title="periodo"), alt.Tooltip("txt:N", title=ETIQ[principal])])
            if dims:
                enc["color"] = alt.Color(f"{dim}:N", title=None, scale=alt.Scale(scheme="tableau10"))
                enc["tooltip"].insert(0, alt.Tooltip(f"{dim}:N"))
                graf = alt.Chart(datos).mark_line(strokeWidth=2).encode(**enc)
            else:
                b = alt.Chart(datos).encode(**enc)
                graf = b.mark_line(color=ACENTO, strokeWidth=2.4) + b.mark_circle(color=ACENTO, size=40)
            st.altair_chart(graf.properties(height=330), width="stretch")
        elif dims:
            datos = df.copy()
            datos["txt"] = datos[principal].map(lambda v: fmt.valor(v, f))
            st.altair_chart(alt.Chart(datos).mark_bar(color=ACENTO, cornerRadiusEnd=3).encode(
                y=alt.Y(f"{dim}:N", sort="-x", title=None), x=alt.X(f"{principal}:Q", title=ETIQ[principal]),
                tooltip=[f"{dim}:N", alt.Tooltip("txt:N", title=ETIQ[principal])]).properties(height=300),
                width="stretch")
        t_datos, t_sql = st.tabs([":material/table: Resultado", ":material/code: SQL compilado"])
        with t_datos:
            vista = df.copy()
            if "periodo" in vista:
                vista["periodo"] = vista.periodo.map(lambda d: etiqueta_periodo(d, g))
            for m in mets:
                vista[m] = vista[m].map(lambda v, m=m: fmt.valor(v, DEF.metricas[m].formato))
            st.dataframe(vista.rename(columns=ETIQ), hide_index=True, width="stretch", height=280)
        with t_sql:
            dialecto = st.radio("Dialecto", DIALECTOS, horizontal=True, label_visibility="collapsed")
            q = Consulta(metricas=list(mets), dimensiones=list(dims), grano=g, desde=str(desde), hasta=str(hasta),
                         filtros={k: list(v) for k, v in filtros.items()})
            st.code(CAPA.sql(q, dialecto), language="sql")
            st.markdown('<div class="nota">El SQL se arma en dialecto DuckDB y sqlglot lo traduce. Los ratios son '
                        '<b>suma/suma</b> en el grano pedido y las dimensiones del maestro entran por '
                        '<b>LEFT JOIN</b>: ningún cobro se pierde.</div>', unsafe_allow_html=True)

# ----------------------------------------------------------------- monitor

with tab_mon:
    c1, c2 = st.columns([1.3, 3])
    met = c1.radio("Métrica", list(SERIE.metrica.unique()), format_func=ETIQ.get,
                   index=list(SERIE.metrica.unique()).index("tasa_aprobacion"))
    s = SERIE[SERIE.metrica == met].sort_values("fecha").copy()
    f = DEF.metricas[met].formato
    s["dia"], valores = eje_mensual(s.fecha)
    valores = valores[::2]  # un mes sí, otro no: con todos se encimarían
    s["v_txt"] = s.valor.map(lambda v: fmt.valor(v, f))
    s["e_txt"] = s.esperado.map(lambda v: fmt.valor(v, f))
    eje = alt.X("dia:O", sort=list(s.dia), title=None,
                axis=alt.Axis(values=valores, labelExpr="slice(datum.label, 3)", labelAngle=0, ticks=False))
    yfmt = ".1%" if f.startswith("porcentaje") else "~s"
    base = alt.Chart(s).encode(x=eje)
    banda = base.mark_area(color=ACENTO, opacity=0.10).encode(
        y=alt.Y("banda_baja:Q", title=None, scale=alt.Scale(zero=False), axis=alt.Axis(format=yfmt)), y2="banda_alta:Q")
    esperado = base.mark_line(color=GRIS, strokeWidth=1, strokeDash=[3, 3]).encode(y="esperado:Q")
    real = base.mark_line(color=ACENTO, strokeWidth=1.4).encode(
        y="valor:Q", tooltip=[alt.Tooltip("dia:N", title="día"), alt.Tooltip("v_txt:N", title="real"),
                              alt.Tooltip("e_txt:N", title="esperado"), alt.Tooltip("z:Q", format="+.1f")])
    alertas = alt.Chart(s[s.alerta]).mark_point(color=ROJO, size=70, filled=True, opacity=1).encode(
        x=eje, y="valor:Q", tooltip=[alt.Tooltip("dia:N", title="día"), alt.Tooltip("v_txt:N", title="real"),
                                     alt.Tooltip("e_txt:N", title="esperado"), alt.Tooltip("z:Q", format="+.1f")])
    with c2:
        st.altair_chart((banda + esperado + real + alertas).properties(height=320), width="stretch")
    c1.markdown(f'<div class="nota">Línea punteada: lo esperado según los 91 días previos. Banda: ±4 '
                f'desviaciones robustas. En rojo: <b>{int(s.alerta.sum())}</b> días con alerta.<br><br>'
                f'Umbral de negocio: <b>{DEF.metricas[met].monitor.umbral_minimo:g}</b> '
                f'({"desvío relativo" if DEF.metricas[met].monitor.modelo == "multiplicativo" else "en nivel"}).</div>',
                unsafe_allow_html=True)

    st.markdown("#### Eventos")
    ev = EVENTOS.copy()
    top = EXPL[EXPL.concentracion >= UMBRAL].groupby(["metrica", "fecha"]).apply(
        lambda g: " · ".join(f"{r.dimension} = {r.segmento}" for r in g.itertuples()), include_groups=False)
    ev["donde"] = [top.get((r.metrica, r.peor_dia), "repartido") for r in ev.itertuples()]
    ev["inc"] = ""
    for r in EVAL.itertuples():
        m = (ev.inicio <= r.fin + pd.Timedelta(days=1)) & (ev.fin >= r.inicio)
        ev.loc[m, "inc"] = r.id_incidente
    ev["metrica"] = ev.metrica.map(ETIQ)
    ev["peor_dia"] = ev.peor_dia.map(lambda d: etiqueta_dia(d, True))
    ev["desvio_txt"] = [fmt.contribucion(x.desvio_peor, "porcentaje") if x.metrica == ETIQ["tasa_aprobacion"]
                        else f"{x.desvio_peor:+.1%}" for x in ev.itertuples()]
    st.dataframe(ev[["peor_dia", "metrica", "dias", "z_peor", "desvio_txt", "donde", "inc"]], hide_index=True,
                 width="stretch", height=(len(ev) + 1) * 35 + 3, column_config={
                     "peor_dia": "peor día", "metrica": "métrica", "dias": "días",
                     "z_peor": st.column_config.NumberColumn("z", format="%+.1f"),
                     "desvio_txt": "desvío", "donde": st.column_config.TextColumn("dónde está el cambio", width="large"),
                     "inc": st.column_config.TextColumn("incidente real", help="Solo existe porque los datos son "
                                                        "sintéticos: el monitor no lee esta tabla.")})
    det = int(EVAL.detectado.sum())
    st.markdown(f'<div class="nota">Contra los incidentes que el generador metió a propósito: <b>{det} de '
                f'{len(EVAL)}</b> detectados, el primero el mismo día en <b>'
                f'{int((EVAL.dias_hasta_alerta == 0).sum())}</b> casos. Días-alerta sin incidente: '
                f'<b>{len(FALSAS)}</b> de {len(SERIE):,} días-métrica.</div>', unsafe_allow_html=True)

# ----------------------------------------------------------------- explicar

with tab_expl:
    opciones = [(r.metrica, r.peor_dia) for r in EVENTOS.itertuples()
                if DEF.metricas[r.metrica].tipo == "ratio" or DEF.medidas[DEF.metricas[r.metrica].medida].aditiva]
    defecto = next(i for i, o in enumerate(opciones) if o[1] == pd.Timestamp("2026-08-14") and o[0] == "tasa_aprobacion")
    c1, c2, c3 = st.columns([2, 1.4, 1.4])
    elegido = c1.selectbox("Alerta", opciones, index=defecto,
                           format_func=lambda o: f"{etiqueta_dia(o[1], True)} · {ETIQ[o[0]]}")
    met, fecha = elegido
    dims_ok = dimensiones_por_defecto(CAPA, met)
    filtro_dim = c2.selectbox("Filtrar por", ["(sin filtro)"] + dims_ok)
    filtro_val = None
    if filtro_dim != "(sin filtro)":
        vals = consultar(("transacciones",), (filtro_dim,), desde=str(fecha.date()), hasta=str(fecha.date()))[0]
        filtro_val = c3.selectbox("Valor", vals[filtro_dim].astype(str).tolist())
    filtros = ((filtro_dim, (filtro_val,)),) if filtro_val else ()
    e = explicacion_dia(met, fecha, filtros, tuple(d for d in dims_ok if d != filtro_dim))
    f = DEF.metricas[met].formato
    color = "r" if e.cambio < 0 else "v"
    st.markdown(f'<div class="lectura">{ETIQ[met]} · {etiqueta_dia(fecha, True)}'
                f'{" · " + filtro_dim + " = " + filtro_val if filtro_val else ""}<br>'
                f'{fmt.valor(e.valor_base, f)} ({e.descripcion_base}) → <span class="c">{fmt.valor(e.valor_actual, f)}</span>'
                f' <span class="{color}">{fmt.cambio(e.valor_base, e.valor_actual, f)}</span></div>',
                unsafe_allow_html=True)

    izq, der = st.columns([1, 1.3])
    rk = e.ranking.copy()
    rk["color"] = [ACENTO if c >= UMBRAL else GRIS_OSCURO for c in rk.concentracion]
    with izq:
        st.markdown("#### Concentración por dimensión")
        st.altair_chart(alt.Chart(rk).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("dimension:N", sort=list(rk.dimension), title=None),
            x=alt.X("concentracion:Q", title=None, scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("color:N", scale=None),
            tooltip=["dimension:N", "segmento:N", alt.Tooltip("concentracion:Q", format=".2f")]
        ).properties(height=300) + alt.Chart(pd.DataFrame({"x": [UMBRAL]})).mark_rule(
            color=AMBAR, strokeDash=[4, 4]).encode(x="x:Q"), width="stretch")
        st.markdown(f'<div class="nota">0: el cambio se reparte como el volumen. Cerca de 1: está en pocos '
                    f'segmentos. Desde <b>{UMBRAL}</b> (línea ámbar) se considera que la dimensión lo explica.</div>',
                    unsafe_allow_html=True)
    with der:
        dim_sel = st.selectbox("Segmentos de", list(rk.dimension), index=0, key="dim_detalle")
        d = e.detalle[dim_sel].copy().head(12)
        d["segmento"] = d.index.astype(str)
        d = d.melt(id_vars=["segmento", "contribucion"], value_vars=["efecto_tasa", "efecto_mezcla"],
                   var_name="efecto", value_name="aporte")
        d["efecto"] = d.efecto.map({"efecto_tasa": "tasa", "efecto_mezcla": "mezcla"})
        d["txt"] = d.aporte.map(lambda v: fmt.contribucion(v, f))
        orden = list(dict.fromkeys(d.segmento))
        st.altair_chart(alt.Chart(d).mark_bar().encode(
            y=alt.Y("segmento:N", sort=orden, title=None, axis=alt.Axis(labelLimit=180, labelOverlap=False)),
            x=alt.X("aporte:Q", title="aporte al cambio",
                    axis=alt.Axis(format=".1%" if f.startswith("porcentaje") else "~s")),
            color=alt.Color("efecto:N", title=None, scale=alt.Scale(domain=["tasa", "mezcla"], range=[ACENTO, AMBAR]),
                            legend=alt.Legend(orient="bottom")),
            tooltip=["segmento:N", "efecto:N", alt.Tooltip("txt:N", title="aporte")]).properties(height=340),
            width="stretch")
    vista = e.ranking[["dimension", "concentracion", "segmento", "contribucion", "parte_del_cambio", "peso_segmento"]].copy()
    vista["contribucion"] = vista.contribucion.map(lambda v: fmt.contribucion(v, f))
    vista[["parte_del_cambio", "peso_segmento"]] *= 100
    st.dataframe(vista, hide_index=True, width="stretch", column_config={
        "dimension": "dimensión", "concentracion": st.column_config.ProgressColumn(
            "concentración", min_value=0, max_value=1, format="%.2f"),
        "segmento": "segmentos que lo llevan", "contribucion": "aportan",
        "parte_del_cambio": st.column_config.NumberColumn("del cambio", format="%.0f%%"),
        "peso_segmento": st.column_config.NumberColumn("peso", format="%.0f%%")})

# ----------------------------------------------------------------- catálogo

with tab_cat:
    filas = []
    for n, m in DEF.metricas.items():
        filas.append({"métrica": n, "etiqueta": m.etiqueta, "tipo": m.tipo,
                      "definición": {"simple": m.medida, "ratio": f"{m.numerador} / {m.denominador}",
                                     "derivada": m.expr}[m.tipo],
                      "aditiva": "sí" if m.tipo == "simple" and DEF.medidas[m.medida].aditiva else "no",
                      "responsable": m.responsable, "monitor": m.monitor.modelo if m.monitor else "",
                      "descripción": m.descripcion})
    st.markdown("#### Métricas")
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
    st.markdown("#### Dimensiones")
    st.dataframe(pd.DataFrame([{"dimensión": d, "modelo": DEF.modelo_de_dimension(d), "expresión": DEF.dimension(d).expr,
                                "explicable": "sí" if DEF.dimension(d).explicable else "no",
                                "deriva": "sí" if DEF.dimension(d).deriva else "",
                                "descripción": DEF.dimension(d).descripcion} for d in DEF.dimensiones()]),
                 hide_index=True, width="stretch")
    with st.expander("semantica/tinkuy.yml", icon=":material/description:"):
        st.code(ruta_semantica().read_text(encoding="utf-8"), language="yaml")
