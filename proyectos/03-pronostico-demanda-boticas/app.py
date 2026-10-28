"""
Tablero de pronóstico y reposición sobre los resultados del backtest.

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

from demanda.calendario import MESES, etiqueta_dia  # noqa: E402
from demanda.rutas import ruta_db, ruta_resultados  # noqa: E402

st.set_page_config(page_title="demanda · Boticas Alameda", page_icon=":material/medication:", layout="wide")

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
POLITICAS = {"regla_actual": "Regla actual", "pronostico": "Pronóstico sin margen",
             "pronostico_p90": "Pronóstico + margen P90", "pronostico_p95": "Pronóstico + margen P95"}
MODELOS = {"promedio_28": "Promedio 28 días (regla actual)", "naive_estacional": "Naive estacional",
           "lgbm_sin_tratar": "LightGBM sin tratar quiebres", "lgbm": "LightGBM"}


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
    # se abre y cierra en cada consulta para no bloquear el archivo mientras corre la CLI
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


DB, RES = ruta_db(), ruta_resultados()
if not DB.exists() or not RES.exists():
    st.error("Faltan los datos o los resultados.", icon=":material/database:")
    st.code("python -m demanda todo", language="bash")
    st.stop()


@st.cache_data(show_spinner=False)
def catalogos():
    loc = consultar(DB, "SELECT id_local, nombre, ciudad, region, formato FROM locales ORDER BY id_local")
    prod = consultar(DB, "SELECT id_producto, nombre, categoria FROM productos ORDER BY categoria, nombre")
    ult = consultar(DB, "SELECT MAX(fecha) AS f FROM ventas_diarias").f.iloc[0]
    return loc, prod, pd.Timestamp(ult)


@st.cache_data(show_spinner=False)
def tabla(nombre: str) -> pd.DataFrame:
    return consultar(RES, f"SELECT * FROM {nombre}")


LOCALES, PRODUCTOS, ULTIMO = catalogos()
CORRIDA = tabla("corrida").iloc[0]
MOD = tabla("metricas_modelos").set_index("modelo")
COB = tabla("cobertura_intervalos").set_index("segmento")
SIM = tabla("simulacion_resumen").set_index("politica")

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Boticas Alameda")
    st.caption(f"{len(LOCALES)} locales · {len(PRODUCTOS)} productos · ene 2024 a "
               f"{MESES[ULTIMO.month - 1]} {ULTIMO.year} · cadena y datos ficticios")
    id_local = st.selectbox("Local", LOCALES.id_local, format_func=lambda i: LOCALES.set_index("id_local").nombre[i],
                            index=0)
    id_producto = st.selectbox(
        "Producto", PRODUCTOS.id_producto,
        index=int(PRODUCTOS.index[PRODUCTOS.nombre.str.startswith("Jarabe para la tos adulto")][0]),
        format_func=lambda i: PRODUCTOS.set_index("id_producto").nombre[i])
    st.subheader("Última corrida")
    st.markdown(
        f'<div class="nota">{pd.Timestamp(CORRIDA.fecha):%d/%m/%Y %H:%M}<br>'
        f'<b>{CORRIDA.cortes}</b> cortes · {pd.Timestamp(CORRIDA.primer_corte):%d/%m} a '
        f'{pd.Timestamp(CORRIDA.ultimo_corte):%d/%m/%Y}<br><b>{CORRIDA.filas:,}</b> predicciones · '
        f'{CORRIDA.segundos / 60:.1f} min</div>', unsafe_allow_html=True)

loc = LOCALES.set_index("id_local").loc[id_local]
prod = PRODUCTOS.set_index("id_producto").loc[id_producto]

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> demanda</p>', unsafe_allow_html=True)
st.caption("Pronóstico diario por local y producto con LightGBM, intervalos conformal y simulación del "
           "pedido semanal. Todas las cifras salen del backtest: entrenado hasta cada corte y medido después.")
st.markdown(
    f'<div class="estado"><b>●</b> duckdb · {DB.name} · datos al {ULTIMO:%d/%m/%Y} · '
    f'backtest {CORRIDA.cortes} cortes x 14 días · lightgbm tweedie</div>', unsafe_allow_html=True)
st.write("")

m1, m2, m3, m4, m5 = st.columns(5)
w_l, w_a = MOD.loc["lgbm", "wape"], MOD.loc["promedio_28", "wape"]
m1.metric("WAPE diario", f"{w_l:.1%}", f"{(w_l - w_a) * 100:+.1f} pp", delta_color="inverse",
          delta_description="vs actual",
          help="Error absoluto / venta, por día, local y producto, en días sin quiebre.")
ws_l, ws_a = MOD.loc["lgbm", "wape_semana"], MOD.loc["promedio_28", "wape_semana"]
m2.metric("WAPE semanal", f"{ws_l:.1%}", f"{(ws_l - ws_a) * 100:+.1f} pp", delta_color="inverse",
          delta_description="vs actual",
          help="Lo mismo, sumando la semana por local y producto: es el nivel al que se decide el pedido.")
m3.metric("Cobertura P10-P90", f"{COB.loc['total', 'cobertura']:.1%}", "objetivo 80%", delta_color="off",
          delta_arrow="off", help="Días en que la venta cayó dentro del intervalo.")
s_a, s_p = SIM.loc["regla_actual"], SIM.loc["pronostico_p95"]
m4.metric("Nivel de servicio", f"{s_p.nivel_servicio:.1%}",
          f"{(s_p.nivel_servicio - s_a.nivel_servicio) * 100:+.1f} pp", delta_description="vs actual",
          help="Unidades vendidas / demandadas en la simulación, con el pronóstico + margen P95.")
m5.metric("Inventario", f"S/ {s_p.inventario_promedio / 1000:,.0f} mil",
          f"{s_p.inventario_promedio / s_a.inventario_promedio - 1:+.1%}", delta_color="inverse",
          delta_description="vs actual",
          help="Stock valorizado al costo, promedio diario de la cadena.")

st.write("")
tab_pron, tab_bt, tab_rep, tab_ped = st.tabs([
    ":material/show_chart: Pronóstico", ":material/fact_check: Backtest",
    ":material/inventory_2: Reposición", ":material/list_alt: Pedido sugerido",
])

# ----------------------------------------------------------------- pronóstico

with tab_pron:
    desde = ULTIMO - pd.Timedelta(days=105)
    hist = consultar(DB, """
        SELECT fecha, unidades, stock_cierre = 0 AS quiebre FROM ventas_diarias
        WHERE id_local = ? AND id_producto = ? AND fecha > ? ORDER BY fecha""", [id_local, id_producto, desde])
    bt = consultar(RES, """
        SELECT fecha, lgbm, lgbm_p10, lgbm_p90 FROM predicciones
        WHERE id_local = ? AND id_producto = ? AND horizonte <= 14 AND fecha > ? ORDER BY fecha""",
                   [id_local, id_producto, desde])
    fut = consultar(RES, """
        SELECT fecha, pronostico, p10, p90, descuento FROM pronostico
        WHERE id_local = ? AND id_producto = ? ORDER BY fecha""", [id_local, id_producto])

    for df in (hist, bt, fut):
        df["fecha"] = pd.to_datetime(df.fecha)
    dias = pd.date_range(hist.fecha.min(), fut.fecha.max(), freq="D")
    orden = [etiqueta_dia(d) for d in dias]
    for df in (hist, bt, fut):
        df["dia"] = df.fecha.map(etiqueta_dia)
    marcas = [etiqueta_dia(d) for d in dias if d.day in (1, 15)]
    eje_x = alt.X("dia:O", sort=orden, title=None,
                  axis=alt.Axis(values=marcas, labelAngle=0, grid=False, ticks=False))

    st.markdown(f"#### {prod.nombre} · {loc.nombre}")
    banda = pd.concat([bt.rename(columns={"lgbm_p10": "lo", "lgbm_p90": "hi"})[["dia", "lo", "hi"]],
                       fut.rename(columns={"p10": "lo", "p90": "hi"})[["dia", "lo", "hi"]]])
    capa_banda = alt.Chart(banda.dropna()).mark_area(color=ACENTO, opacity=0.12, interpolate="monotone"
                                                    ).encode(x=eje_x, y="lo:Q", y2="hi:Q")
    real = alt.Chart(hist).mark_line(color=GRIS, strokeWidth=1.3, opacity=0.85).encode(
        x=eje_x, y=alt.Y("unidades:Q", title="unidades por día", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("dia:N", title="día"), alt.Tooltip("unidades:Q", title="venta")])
    quiebres = alt.Chart(hist[hist.quiebre]).mark_point(color=AMBAR, size=40, filled=True, shape="triangle-down"
                                                         ).encode(x=eje_x, y="unidades:Q",
                                                                  tooltip=[alt.Tooltip("dia:N", title="quiebre")])
    linea_bt = alt.Chart(bt).mark_line(color=ACENTO, strokeWidth=1.6, opacity=0.8, interpolate="monotone").encode(
        x=eje_x, y="lgbm:Q", tooltip=[alt.Tooltip("dia:N", title="día"),
                                      alt.Tooltip("lgbm:Q", title="pronóstico backtest", format=".1f")])
    linea_fut = alt.Chart(fut).mark_line(color=ACENTO, strokeWidth=2.6, interpolate="monotone").encode(
        x=eje_x, y="pronostico:Q",
        tooltip=[alt.Tooltip("dia:N", title="día"), alt.Tooltip("pronostico:Q", format=".1f"),
                 alt.Tooltip("p10:Q", format=".1f"), alt.Tooltip("p90:Q", format=".1f")])
    hoy = alt.Chart(pd.DataFrame({"dia": [etiqueta_dia(ULTIMO)], "t": ["hoy"]}))
    regla = hoy.mark_rule(color=GRIS_OSCURO, strokeDash=[4, 4]).encode(x=eje_x)
    st.altair_chart((capa_banda + real + linea_bt + linea_fut + quiebres + regla).properties(height=340),
                    width="stretch")
    st.markdown(
        '<div class="nota">Gris: venta real · <b style="color:#22D3EE">cian fino</b>: pronóstico del backtest '
        '(hecho en cada corte, sin ver lo que venía) · <b style="color:#22D3EE">cian grueso</b>: próximos 14 días · '
        'banda: P10-P90 conformal · <b style="color:#FBBF24">▼</b> quiebre de stock: ese día la venta no es la demanda'
        '</div>', unsafe_allow_html=True)

    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    sel = bt.merge(hist, on="dia")
    sel = sel[~sel.quiebre]
    if len(sel) and sel.unidades.sum():
        c1.metric("WAPE de esta serie", f"{(sel.lgbm - sel.unidades).abs().sum() / sel.unidades.sum():.1%}",
                  help="Backtest, últimos 105 días, sin días de quiebre.")
    c2.metric("Quiebres (105 días)", f"{int(hist.quiebre.sum())}")
    c3.metric("Próximos 14 días", f"{fut.pronostico.sum():.0f} u",
              f"P10 {fut.p10.sum():.0f} · P90 {fut.p90.sum():.0f}", delta_color="off", delta_arrow="off",
              help="La suma de los P10 y P90 diarios no es el P10/P90 de la suma: es solo referencia.")
    c4.metric("Días con promoción", f"{int((fut.descuento > 0).sum())} de 14")

# ----------------------------------------------------------------- backtest

with tab_bt:
    col_a, col_b = st.columns([1.1, 1])
    with col_a:
        st.markdown("#### Error por modelo")
        mm = MOD.reset_index()
        mm["nombre"] = mm.modelo.map(MODELOS)
        mm = mm.melt(id_vars=["nombre", "modelo"], value_vars=["wape", "wape_semana"], var_name="nivel",
                     value_name="valor")
        mm["nivel"] = mm.nivel.map({"wape": "diario", "wape_semana": "semanal"})
        mm["etiqueta"] = mm.valor.map(lambda x: f"{x:.1%}")
        orden_m = [MODELOS[m] for m in ["lgbm", "lgbm_sin_tratar", "promedio_28", "naive_estacional"]]
        enc = alt.Chart(mm).encode(
            y=alt.Y("nombre:N", sort=orden_m, title=None, axis=alt.Axis(labelLimit=260)),
            yOffset=alt.YOffset("nivel:N", sort=["diario", "semanal"]),
            x=alt.X("valor:Q", title="WAPE", axis=alt.Axis(format="%")),
        )
        barras = enc.mark_bar(cornerRadiusEnd=3, height=13).encode(
            color=alt.Color("nivel:N", scale=alt.Scale(domain=["diario", "semanal"], range=[ACENTO, GRIS_OSCURO]),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["nombre", "nivel", alt.Tooltip("valor:Q", format=".1%")])
        texto = enc.mark_text(align="left", dx=4, font="JetBrains Mono", fontSize=11, color="#D6DEE6"
                              ).encode(text="etiqueta:N")
        st.altair_chart((barras + texto).properties(height=260), width="stretch")
        st.caption("Días sin quiebre de los primeros 14 días de cada corte. El nivel semanal suma la venta de "
                   "la semana por local y producto, que es como se decide el pedido.")
    with col_b:
        st.markdown("#### Cuánto se queda corto en los días de quiebre")
        sq = MOD.reset_index()[["modelo", "sesgo", "sesgo_en_quiebres"]]
        sq["nombre"] = sq.modelo.map(MODELOS)
        sq["corto"] = -sq.sesgo_en_quiebres
        sq["etiqueta"] = sq.corto.map(lambda x: f"{x:.1%}")
        enc = alt.Chart(sq).encode(y=alt.Y("nombre:N", sort=orden_m, title=None, axis=alt.Axis(labelLimit=260)),
                                   x=alt.X("corto:Q", title="subestimación de la demanda latente",
                                           axis=alt.Axis(format="%")))
        b = enc.mark_bar(cornerRadiusEnd=3, height=20).encode(
            color=alt.condition(alt.datum.modelo == "lgbm", alt.value(ACENTO), alt.value(GRIS_OSCURO)),
            tooltip=["nombre", alt.Tooltip("sesgo_en_quiebres:Q", title="sesgo", format="+.1%")])
        t = enc.mark_text(align="left", dx=4, font="JetBrains Mono", fontSize=11, color="#D6DEE6"
                          ).encode(text="etiqueta:N")
        st.altair_chart((b + t).properties(height=260), width="stretch")
        st.caption("En un día de quiebre la venta subestima la demanda. Comparando contra la demanda latente "
                   "del generador (que en la vida real no existe) se ve quién se queda más corto.")

    col_c, col_d = st.columns([1.3, 1])
    with col_c:
        st.markdown("#### Por categoría")
        cat = tabla("metricas_categorias").sort_values("unidades", ascending=False)
        cat = cat[["categoria", "unidades", "wape_promedio_28", "wape_lgbm", "mejora"]]
        for c in ("wape_promedio_28", "wape_lgbm", "mejora"):
            cat[c] = cat[c] * 100
        st.dataframe(cat, hide_index=True, width="stretch", column_config={
            "categoria": "categoría",
            "unidades": st.column_config.NumberColumn("unidades", format="localized"),
            "wape_promedio_28": st.column_config.NumberColumn("WAPE regla actual", format="%.1f%%"),
            "wape_lgbm": st.column_config.NumberColumn("WAPE LightGBM", format="%.1f%%"),
            "mejora": st.column_config.NumberColumn("mejora", format="%.1f%%"),
        })
    with col_d:
        st.markdown("#### Variables más usadas")
        imp = tabla("importancia").head(10)
        b = alt.Chart(imp).mark_bar(color=ACENTO, cornerRadiusEnd=3).encode(
            y=alt.Y("variable:N", sort="-x", title=None, axis=alt.Axis(labelFont="JetBrains Mono")),
            x=alt.X("ganancia:Q", title="ganancia (fracción)", axis=alt.Axis(format="%")),
            tooltip=["variable", alt.Tooltip("ganancia:Q", format=".1%")])
        st.altair_chart(b.properties(height=280), width="stretch")

    st.markdown("#### Cobertura del intervalo P10-P90 por rotación")
    cob = tabla("cobertura_intervalos")
    st.dataframe(cob, hide_index=True, width="stretch", column_config={
        "cobertura": st.column_config.ProgressColumn("cobertura", format="percent", min_value=0, max_value=1),
        "ancho_medio": st.column_config.NumberColumn("ancho medio (u)", format="%.1f"),
        "filas": st.column_config.NumberColumn("días evaluados", format="localized"),
    })

# ----------------------------------------------------------------- reposición

with tab_rep:
    diario = tabla("simulacion_diaria")
    diario["fecha"] = pd.to_datetime(diario.fecha)
    inicio, fin = diario.fecha.min(), diario.fecha.max()
    # por semana (lunes): el día a día tiene un serrucho que solo refleja la llegada del pedido
    diario["semana"] = diario.fecha - pd.to_timedelta(diario.fecha.dt.dayofweek, unit="D")
    semanal = (diario.groupby(["politica", "semana"])
               .agg(quiebres=("quiebres", "mean"), inventario=("inventario", "mean"), dias=("fecha", "size"))
               .reset_index())
    semanal = semanal[semanal.dias == 7]
    semanal["nombre"] = semanal.politica.map(POLITICAS)
    semanal["dia"] = semanal.semana.map(etiqueta_dia)
    orden_d = [etiqueta_dia(d) for d in sorted(semanal.semana.unique())]
    marcas = orden_d[::3]
    eje = alt.X("dia:O", sort=orden_d, title="semana que empieza el", axis=alt.Axis(values=marcas, labelAngle=0,
                                                                                    grid=False))
    colores = alt.Scale(domain=list(POLITICAS.values()), range=[GRIS, GRIS_OSCURO, "#0E7490", ACENTO])
    leyenda = alt.Legend(orient="top", title=None, columns=2, labelLimit=220)

    st.markdown(f"#### Misma demanda, cuatro reglas de pedido · {etiqueta_dia(inicio)} a {etiqueta_dia(fin)} "
                f"{fin.year}")
    res = tabla("simulacion_resumen")
    res["politica"] = res.politica.map(POLITICAS)
    res["nivel_servicio"] *= 100
    res["dias_con_quiebre"] *= 100
    res["venta_perdida"] = res.venta_perdida.round().astype(int)
    res["inventario_promedio"] = res.inventario_promedio.round().astype(int)
    st.dataframe(res, hide_index=True, width="stretch", column_config={
        "politica": "política",
        "nivel_servicio": st.column_config.NumberColumn("nivel de servicio", format="%.1f%%"),
        "dias_con_quiebre": st.column_config.NumberColumn("días con quiebre", format="%.1f%%"),
        "venta_perdida": st.column_config.NumberColumn("venta perdida (S/)", format="localized"),
        "inventario_promedio": st.column_config.NumberColumn("inventario prom. al costo (S/)", format="localized"),
        "dias_de_inventario": st.column_config.NumberColumn("días de inventario", format="%.1f"),
    })

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Local-producto en quiebre, promedio semanal")
        g = alt.Chart(semanal).mark_line(strokeWidth=2.2, interpolate="monotone", point=alt.OverlayMarkDef(size=28)).encode(
            x=eje, y=alt.Y("quiebres:Q", title="% de local-producto sin stock", axis=alt.Axis(format="%"),
                           scale=alt.Scale(zero=False)),
            color=alt.Color("nombre:N", scale=colores, legend=leyenda),
            tooltip=["nombre", alt.Tooltip("dia:N", title="semana"), alt.Tooltip("quiebres:Q", format=".1%")])
        st.altair_chart(g.properties(height=280), width="stretch")
    with col_b:
        st.markdown("#### Inventario al costo, promedio semanal")
        g = alt.Chart(semanal).mark_line(strokeWidth=2.2, interpolate="monotone", point=alt.OverlayMarkDef(size=28)).encode(
            x=eje, y=alt.Y("inventario:Q", title="S/ al costo", scale=alt.Scale(zero=False),
                           axis=alt.Axis(format=",.0f")),
            color=alt.Color("nombre:N", scale=colores, legend=leyenda),
            tooltip=["nombre", alt.Tooltip("dia:N", title="semana"), alt.Tooltip("inventario:Q", format=",.0f")])
        st.altair_chart(g.properties(height=280), width="stretch")

    st.markdown("#### Por categoría: regla actual vs pronóstico + margen P95")
    sc = tabla("simulacion_categorias")
    piv = sc.pivot(index="categoria", columns="politica",
                   values=["nivel_servicio", "dias_de_inventario", "venta_perdida"])
    piv = pd.DataFrame({
        "categoría": piv.index,
        "servicio actual": piv[("nivel_servicio", "regla_actual")].to_numpy(),
        "servicio P95": piv[("nivel_servicio", "pronostico_p95")].to_numpy(),
        "días inv. actual": piv[("dias_de_inventario", "regla_actual")].to_numpy(),
        "días inv. P95": piv[("dias_de_inventario", "pronostico_p95")].to_numpy(),
        "venta perdida actual (S/)": piv[("venta_perdida", "regla_actual")].to_numpy(),
        "venta perdida P95 (S/)": piv[("venta_perdida", "pronostico_p95")].to_numpy(),
    }).sort_values("venta perdida actual (S/)", ascending=False)
    for c in piv.columns:
        if "servicio" in c:
            piv[c] = piv[c] * 100
        if "S/" in c:
            piv[c] = piv[c].round().astype(int)
    fmt = {c: st.column_config.NumberColumn(c, format="%.1f%%") for c in piv.columns if "servicio" in c}
    fmt |= {c: st.column_config.NumberColumn(c, format="%.1f") for c in piv.columns if "días" in c}
    fmt |= {c: st.column_config.NumberColumn(c, format="localized") for c in piv.columns if "S/" in c}
    st.dataframe(piv, hide_index=True, width="stretch", column_config=fmt)

# ----------------------------------------------------------------- pedido

with tab_ped:
    ped = consultar(RES, """
        SELECT nombre, categoria, demanda_esperada, stock_cierre, en_transito, stock_objetivo, pedido,
               costo_pedido, dias_de_stock
        FROM pedido_sugerido WHERE id_local = ? ORDER BY costo_pedido DESC""", [id_local])
    n_dias = 6 + {"Lima": 2}.get(loc.region, 4)
    st.markdown(f"#### Pedido sugerido · {loc.nombre} · corte {ULTIMO:%d/%m/%Y}")
    p1, p2, p3 = st.columns(3)
    p1.metric("Productos a pedir", f"{int((ped.pedido > 0).sum())} de {len(ped)}")
    p2.metric("Unidades", f"{int(ped.pedido.sum()):,}")
    p3.metric("Costo del pedido", f"S/ {ped.costo_pedido.sum():,.0f}")
    st.caption(f"Stock objetivo = P95 de la demanda de los próximos {n_dias} días (una semana más el lead "
               f"time de {n_dias - 6} días), calibrado con los errores del backtest. Pedido = objetivo - stock - "
               "en tránsito.")
    st.dataframe(ped, hide_index=True, width="stretch", height=460, column_config={
        "nombre": "producto", "categoria": "categoría",
        "demanda_esperada": st.column_config.NumberColumn("demanda esperada", format="%.1f"),
        "stock_cierre": st.column_config.NumberColumn("stock"),
        "en_transito": st.column_config.NumberColumn("en tránsito"),
        "stock_objetivo": st.column_config.NumberColumn("objetivo P95", format="%d"),
        "pedido": st.column_config.NumberColumn("pedido", format="%d"),
        "costo_pedido": st.column_config.NumberColumn("costo (S/)", format="%.2f"),
        "dias_de_stock": st.column_config.NumberColumn("días de stock", format="%.1f"),
    })
    st.download_button("Descargar CSV", ped.to_csv(index=False).encode("utf-8"),
                       f"pedido_local_{id_local}.csv", "text/csv", icon=":material/download:")
