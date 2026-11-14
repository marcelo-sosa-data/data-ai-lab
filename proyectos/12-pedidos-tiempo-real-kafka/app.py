"""
Tablero de la torre de control: tablero actual contra streaming, cola por
zona en cada incidente, efecto de la gracia y vista en vivo.

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

from pedidos_rt.config import DIR_DATOS, Ajustes  # noqa: E402

st.set_page_config(page_title="torre de control · Wayki", page_icon=":material/two_wheeler:", layout="wide")

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
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO = "#22D3EE"
GRIS = "#7D8B99"
AMBAR = "#FBBF24"
ROJO = "#F87171"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
AS_IS = "Tablero cada 15 min, % demoradas (AS IS)"
TO_BE = "Streaming, cola al minuto (TO BE)"
REGLA = Ajustes().regla


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


def dia_corto(f) -> str:
    f = pd.Timestamp(f)
    return f"{DIAS[f.weekday()]} {f.day} {MESES[f.month - 1]}"


def leer_parquet(carpeta: Path) -> pd.DataFrame:
    archivos = sorted(carpeta.glob("*.parquet"))
    if not archivos:
        return pd.DataFrame()
    con = duckdb.connect()
    return con.execute(f"SELECT * FROM read_parquet({[a.as_posix() for a in archivos]})").df()


@st.cache_data(show_spinner=False)
def cargar(marca: float):
    with duckdb.connect(str(DIR_DATOS / "resultados.duckdb"), read_only=True) as con:
        tablas = {t: con.execute(f"SELECT * FROM {t}").df()
                  for (t,) in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    tablas["cola"] = leer_parquet(Ajustes().dir_salida / "gracia_060s" / "cola")
    tablas["incidentes"] = pd.read_parquet(DIR_DATOS / "incidentes.parquet")
    return tablas


ruta_res = DIR_DATOS / "resultados.duckdb"
st.markdown('<p class="encabezado"><span>&gt;</span> torre de control</p>', unsafe_allow_html=True)
st.caption("Wayki, delivery en 12 zonas de Lima. Semana del 5 al 11 de octubre de 2026, datos sintéticos.")

if not ruta_res.exists():
    st.warning("No hay resultados. Levanta el broker y corre `python -m pedidos_rt todo`.",
               icon=":material/warning:")
    st.stop()

T = cargar(ruta_res.stat().st_mtime)
res = T["resumen"].set_index("variante")
num = ["detectados", "incidentes", "falsas_alarmas", "pedidos_antes_alerta", "cancelados_antes_alerta"]
a, b = ({k: (int(v) if k in num else v) for k, v in res.loc[x].items()} for x in (AS_IS, TO_BE))
st.markdown(
    f'<div class="estado"><b>●</b> redpanda · quix streams · ventana 1 min · '
    f'alerta con {REGLA.umbral_sin_motorizado}+ pedidos sin motorizado hace más de '
    f'{int(REGLA.espera_sin_motorizado_s // 60)} min</div>', unsafe_allow_html=True)
st.write("")

tab_comp, tab_zona, tab_gracia, tab_vivo = st.tabs([
    ":material/compare_arrows: Antes y después", ":material/map: Incidente por incidente",
    ":material/timer: Gracia de la ventana", ":material/sensors: En vivo"])

# ----------------------------------------------------------------- comparación
with tab_comp:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mediana hasta la alerta", f"{b['demora_mediana_min']:.0f} min",
              f"{b['demora_mediana_min'] - a['demora_mediana_min']:+.0f} min vs tablero", delta_color="inverse")
    c2.metric("Incidentes detectados", f"{b['detectados']}/{b['incidentes']}",
              f"{b['detectados'] - a['detectados']:+d} vs tablero")
    c3.metric("Alertas sin incidente", f"{b['falsas_alarmas']}",
              f"{b['falsas_alarmas'] - a['falsas_alarmas']:+d} vs tablero", delta_color="inverse")
    c4.metric("Pedidos antes de la alerta", f"{b['pedidos_antes_alerta']:,}",
              f"{b['pedidos_antes_alerta'] - a['pedidos_antes_alerta']:+,} vs tablero", delta_color="inverse")

    st.markdown("#### Todas las formas de vigilar")
    tabla = T["resumen"].rename(columns={
        "variante": "Variante", "detectados": "Detectados", "demora_mediana_min": "Mediana (min)",
        "demora_max_min": "Máxima (min)", "falsas_alarmas": "Falsas", "pedidos_antes_alerta":
        "Pedidos antes de la alerta", "cancelados_antes_alerta": "Cancelados antes"})
    st.dataframe(tabla.drop(columns=["incidentes", "falsas_por_dia"]), hide_index=True, width="stretch")
    st.markdown('<p class="nota">Las dos filas del medio separan los cambios: la métrica (cola en vez de '
                '% demoradas) y la cadencia (cada minuto en vez de cada 15). La referencia aplica la '
                'misma regla con la hora real de cada evento.</p>', unsafe_allow_html=True)

    st.markdown("#### Minutos desde que empezó el incidente hasta la alerta")
    det = T["detalle"]
    det = det[det["variante"].isin([AS_IS, TO_BE])].copy()
    det["etiqueta"] = det["incidente"] + " " + det["zona"]
    det["proceso"] = det["variante"].map({AS_IS: "Tablero actual", TO_BE: "Streaming"})
    det["texto"] = det["demora_min"].map(lambda x: "no detectó" if pd.isna(x) else f"{x:.0f}")
    base = alt.Chart(det).encode(
        y=alt.Y("etiqueta:N", title=None, sort=list(det["etiqueta"].unique())),
        yOffset="proceso:N",
        color=alt.Color("proceso:N", title=None, scale=alt.Scale(
            domain=["Tablero actual", "Streaming"], range=[GRIS, ACENTO]),
            legend=alt.Legend(orient="top")),
    )
    barras = base.mark_bar(cornerRadiusEnd=3, height=9).encode(
        x=alt.X("demora_min:Q", title="minutos"),
        tooltip=["incidente", "zona", "causa", "proceso", alt.Tooltip("demora_min:Q", format=".1f")])
    st.altair_chart((barras + base.mark_text(align="left", dx=4, fontSize=10, color="#9AA7B4").encode(
        x=alt.X("demora_min:Q"), text="texto:N")).properties(height=440), width="stretch")

# ----------------------------------------------------------------- por incidente
with tab_zona:
    inc = T["incidentes"]
    opciones = {f"{r.incidente} · {r.zona} · {dia_corto(r.inicio)} {r.inicio:%H:%M} · {r.causa}": r
                for r in inc.itertuples()}
    elegido = opciones[st.selectbox("Incidente", list(opciones))]
    desde = elegido.inicio - pd.Timedelta(minutes=40)
    hasta = elegido.fin + pd.Timedelta(minutes=40)

    cola = T["cola"]
    cola = cola[cola["zona"] == elegido.zona].copy()
    cola["corte"] = pd.to_datetime(cola["inicio_ms"], unit="ms")
    cola = cola[(cola["corte"] >= desde) & (cola["corte"] <= hasta)].sort_values("corte")
    cola["hora"] = cola["corte"].dt.strftime("%H:%M")

    tab = T["tablero"]
    tab = tab[(tab["zona"] == elegido.zona) & (tab["corte"] >= desde) & (tab["corte"] <= hasta)].copy()
    tab["hora"] = pd.to_datetime(tab["corte"]).dt.strftime("%H:%M")

    orden = list(cola["hora"])
    eje = alt.X("hora:O", title=None, sort=orden,
                axis=alt.Axis(labelAngle=0, values=[h for h in orden if h.endswith(("0", "5"))][::2]))
    banda = alt.Chart(pd.DataFrame({"a": [elegido.inicio.strftime("%H:%M")],
                                    "b": [elegido.fin.strftime("%H:%M")]})).mark_rect(
        color=ROJO, opacity=0.08).encode(x=alt.X("a:O", sort=orden), x2="b:O")
    linea = alt.Chart(cola).mark_line(color=ACENTO, strokeWidth=2, interpolate="step-after").encode(
        x=eje, y=alt.Y("sin_motorizado:Q", title="pedidos sin motorizado > 3 min",
                       scale=alt.Scale(zero=False, nice=True)),
        tooltip=["hora", "sin_motorizado"])
    umbral = alt.Chart(pd.DataFrame({"u": [REGLA.umbral_sin_motorizado]})).mark_rule(
        color=AMBAR, strokeDash=[4, 4]).encode(y="u:Q")

    d = T["detalle"]
    d = d[d["incidente"] == elegido.incidente].set_index("variante")
    marcas = []
    for var, nombre, color in ((TO_BE, "alerta streaming", ACENTO), (AS_IS, "alerta tablero", GRIS)):
        t = d.loc[var, "detectado"]
        if pd.notna(t):
            marcas.append({"hora": pd.Timestamp(t).floor("min").strftime("%H:%M"), "quien": nombre, "c": color})
    capas = banda + linea + umbral
    if marcas:
        m = pd.DataFrame(marcas)
        m = m[m["hora"].isin(orden)]
        capas += alt.Chart(m).mark_rule(strokeWidth=2).encode(
            x=alt.X("hora:O", sort=orden), color=alt.Color("c:N", scale=None), tooltip=["quien", "hora"])
    st.altair_chart(capas.properties(height=320), width="stretch")

    c1, c2, c3 = st.columns(3)
    c1.metric("Streaming", "no detectó" if pd.isna(d.loc[TO_BE, "demora_min"]) else f"{d.loc[TO_BE, 'demora_min']:.0f} min")
    c2.metric("Tablero actual", "no detectó" if pd.isna(d.loc[AS_IS, "demora_min"]) else f"{d.loc[AS_IS, 'demora_min']:.0f} min")
    c3.metric("Pedidos de diferencia", f"{int(d.loc[AS_IS, 'pedidos_antes_alerta'] - d.loc[TO_BE, 'pedidos_antes_alerta']):,}")

    st.markdown("#### Lo que mostraba el tablero de 15 minutos")
    st.dataframe(tab[["hora", "creados", "asignados", "demoradas", "ratio_demoradas", "en_rojo"]].rename(
        columns={"hora": "refresco", "ratio_demoradas": "% demoradas", "en_rojo": "en rojo"}),
        hide_index=True, width="stretch",
        column_config={"% demoradas": st.column_config.NumberColumn(format="percent")})

# ----------------------------------------------------------------- gracia
with tab_gracia:
    fl = T["consistencia_flujo"].sort_values("gracia_s").copy()
    fl["fuera"] = fl["asignado_tardios"] / fl["asignado_verdad"]
    fl["gracia"] = fl["gracia_s"].astype(int).astype(str) + " s"
    st.markdown("#### Cuánto se espera cada minuto y qué parte de las asignaciones queda fuera")
    orden_g = list(fl["gracia"])
    g1 = alt.Chart(fl).mark_bar(color=ACENTO, cornerRadiusEnd=3).encode(
        x=alt.X("gracia:O", sort=orden_g, title="gracia", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("retraso_mediano_s:Q", title="segundos hasta publicar (mediana)"),
        tooltip=["gracia", "retraso_mediano_s", "retraso_p90_s"])
    g2 = alt.Chart(fl).mark_bar(color=AMBAR, cornerRadiusEnd=3).encode(
        x=alt.X("gracia:O", sort=orden_g, title="gracia", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("fuera:Q", title="asignaciones fuera de su minuto", axis=alt.Axis(format="%")),
        tooltip=["gracia", alt.Tooltip("fuera:Q", format=".1%"), "asignado_tardios"])
    c1, c2 = st.columns(2)
    c1.altair_chart(g1.properties(height=280), width="stretch")
    c2.altair_chart(g2.properties(height=280), width="stretch")
    st.markdown('<p class="nota">Lo que queda fuera no se pierde: va a la carpeta de tardíos y el cierre '
                'del día lo suma. Con la conciliación los creados y asignados cuadran con el total en '
                'todas las gracias. La alerta no depende de la gracia porque lee la cola al momento.</p>',
                unsafe_allow_html=True)
    ct = T["consistencia_tablero"]
    st.markdown("#### El tablero de 15 minutos contra el cierre")
    st.dataframe(ct.rename(columns={"tipo": "evento", "verdad": "cierre del día", "mostrado": "mostrado",
                                    "reintentos": "reintentos contados", "no_llegaron": "llegaron tarde a su bloque"}),
                 hide_index=True, width="stretch")

# ----------------------------------------------------------------- en vivo
with tab_vivo:
    dir_vivo = Ajustes().dir_salida / "en_vivo"
    st.markdown('<p class="nota">Con el broker arriba, corre <code>python -m pedidos_rt en-vivo</code> '
                'en otra terminal: repite la semana a 60x y esta pestaña se actualiza cada 5 segundos.</p>',
                unsafe_allow_html=True)

    @st.fragment(run_every=5)
    def vista_en_vivo():
        cola = leer_parquet(dir_vivo / "cola")
        if cola.empty:
            st.info("Todavía no hay datos en vivo.", icon=":material/hourglass_empty:")
            return
        alertas = leer_parquet(dir_vivo / "alertas")
        ultimo = cola.sort_values("inicio_ms").groupby("zona").tail(1).copy()
        ultimo["hora"] = pd.to_datetime(ultimo["inicio_ms"], unit="ms").dt.strftime("%H:%M")
        abiertas = set()
        if len(alertas):
            ult = alertas.sort_values("detectado_ms").groupby("zona").tail(1)
            abiertas = set(ult.loc[ult["accion"] == "abrir", "zona"])
        ultimo["estado"] = ultimo["zona"].map(lambda z: "alerta" if z in abiertas else "normal")
        reloj = pd.to_datetime(cola["emitido_ms"].max(), unit="ms")
        st.markdown(f'<div class="estado"><b>●</b> reloj simulado {dia_corto(reloj)} '
                    f'{reloj:%H:%M:%S} · {len(abiertas)} zonas en alerta</div>', unsafe_allow_html=True)
        st.write("")
        g = alt.Chart(ultimo).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("zona:N", title=None, sort="-x"),
            x=alt.X("sin_motorizado:Q", title="pedidos sin motorizado > 3 min",
                    scale=alt.Scale(domain=[0, max(REGLA.umbral_sin_motorizado + 3,
                                                   int(ultimo["sin_motorizado"].max()) + 1)]),
                    axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("estado:N", scale=alt.Scale(domain=["normal", "alerta"], range=[ACENTO, ROJO]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["zona", "hora", "sin_motorizado", "estado"])
        umbral = alt.Chart(pd.DataFrame({"u": [REGLA.umbral_sin_motorizado]})).mark_rule(
            color=AMBAR, strokeDash=[4, 4]).encode(x="u:Q")
        st.altair_chart((g + umbral).properties(height=360), width="stretch")

    vista_en_vivo()
