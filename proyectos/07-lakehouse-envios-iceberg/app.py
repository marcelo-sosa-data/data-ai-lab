"""
Tablero del lakehouse de Kallpa Envíos: estado de las tablas, calidad del CDC, contrato y
cuarentena, viaje en el tiempo sobre oro y efecto del mantenimiento.

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

from pyiceberg.exceptions import NoSuchTableError  # noqa: E402

from lakehouse import catalogo  # noqa: E402
from lakehouse.auditoria import conciliar, ingenuo  # noqa: E402
from lakehouse.bitacora import Bitacora  # noqa: E402
from lakehouse.calendario import MESES, corte_de, etiqueta_corte, etiqueta_dia  # noqa: E402
from lakehouse.contrato import Contrato  # noqa: E402
from lakehouse.mantenimiento import estadisticas  # noqa: E402
from lakehouse.oro import indicadores  # noqa: E402
from lakehouse.rutas import ruta_contrato  # noqa: E402
from lakehouse.viaje import reportado_vs_final, todos_los_cortes  # noqa: E402

st.set_page_config(page_title="lakehouse · Kallpa Envíos", page_icon=":material/local_shipping:", layout="wide")

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
.lectura { font-family: 'JetBrains Mono', monospace; font-size: .9rem; border-radius: 8px; padding: 12px 16px;
           border: 1px solid #1F2A36; background: #0F151C; margin: .2rem 0 .8rem 0; color: #D6DEE6; line-height: 1.7; }
.lectura .c { color: #22D3EE; font-weight: 600; }
.lectura .r { color: #F87171; font-weight: 600; }
.lectura .v { color: #34D399; font-weight: 600; }
.lectura .a { color: #FBBF24; font-weight: 600; }
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO, GRIS, GRIS_OSCURO = "#22D3EE", "#7D8B99", "#2A3542"
ROJO, VERDE, AMBAR, VIOLETA = "#F87171", "#34D399", "#FBBF24", "#A78BFA"


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


NOMBRES = {"bronce": "bronce.cdc_envios", "plata": "plata.envios", "estados": "plata.estados_envio",
           "cuarentena": "plata.cuarentena", "oro": "oro.entregas_diarias"}


@st.cache_resource(show_spinner=False)
def tablas():
    return catalogo.tablas()


try:
    T = tablas()
except NoSuchTableError:
    st.error("Todavía no hay lakehouse.", icon=":material/database:")
    st.code("python -m lakehouse todo", language="bash")
    st.stop()

CONTRATO = Contrato.desde_yaml()


@st.cache_data(show_spinner=False)
def bitacora(tabla: str) -> pd.DataFrame:
    return Bitacora().leer(tabla)


@st.cache_data(show_spinner=False)
def stats() -> pd.DataFrame:
    filas = []
    for k, t in T.items():
        e = estadisticas(t, medir_lectura=False).fila()
        e["marca"] = catalogo.ultimo_lote(t)
        filas.append(e)
    return pd.DataFrame(filas)


@st.cache_data(show_spinner="Leyendo los cortes de oro...")
def cortes_oro() -> pd.DataFrame:
    return todos_los_cortes(T["oro"])


@st.cache_data(show_spinner=False)
def cuarentena() -> pd.DataFrame:
    return T["cuarentena"].scan(selected_fields=("lote", "lsn", "id_envio", "violaciones", "en_historial",
                                                  "despues")).to_pandas()


@st.cache_data(show_spinner="Conciliando con origen...")
def auditoria():
    c = conciliar(T["plata"], T["cuarentena"], CONTRATO)
    m = ingenuo(T["bronce"], T["plata"], CONTRATO)
    return c, m


def dias(fechas) -> list[str]:
    return [etiqueta_dia(d) for d in fechas]


def eje_dias(etiquetas: list[str], cada: int = 7) -> alt.X:
    return alt.X("dia:O", sort=etiquetas, title=None,
                 axis=alt.Axis(values=etiquetas[::cada], labelAngle=0, ticks=False))


LOTES = bitacora("lotes")
MANT = bitacora("mantenimiento")
ST = stats()

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Kallpa Envíos")
    st.caption("Courier ficticio de última milla · Lima, Callao y 7 ciudades · datos sintéticos")
    if len(LOTES):
        st.markdown(f'<div class="nota"><b>{len(LOTES)}</b> lotes de 6 horas<br>'
                    f'{etiqueta_corte(LOTES.lote.min())} a {etiqueta_corte(LOTES.lote.max())}<br>'
                    f'<b>{int(LOTES.eventos.sum()):,}</b> eventos CDC</div>', unsafe_allow_html=True)
    st.subheader("Contrato")
    st.markdown(f'<div class="nota">{CONTRATO.contrato} <b>v{CONTRATO.version}</b><br>dueño: {CONTRATO.dueno}<br>'
                f'<b>{len(CONTRATO.chequeos())}</b> chequeos · umbral de cuarentena '
                f'<b>{CONTRATO.umbral_cuarentena:.0%}</b></div>', unsafe_allow_html=True)
    st.subheader("Catálogo")
    st.markdown('<div class="nota">Iceberg · SqlCatalog (SQLite)<br>pyiceberg + DuckDB<br>'
                'orquestación: Dagster</div>', unsafe_allow_html=True)

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> lakehouse</p>', unsafe_allow_html=True)
st.caption("El CDC de la tabla de envíos llega cada 6 horas. Bronce lo guarda tal cual, plata aplica el contrato "
           "y el orden por lsn, oro publica el cumplimiento de promesa cada mañana y cada corte queda etiquetado.")
marca = ST.set_index("tabla").loc["plata.envios", "marca"]
st.markdown(f'<div class="estado"><b>●</b> iceberg · 5 tablas · plata al corte {etiqueta_corte(marca)} · '
            f'esquema de plata v{len(T["plata"].schemas())} · {len(T["oro"].refs()) - 1} cortes etiquetados</div>',
            unsafe_allow_html=True)
st.write("")

tab_res, tab_cdc, tab_con, tab_viaje, tab_mant = st.tabs([
    ":material/dashboard: Resumen", ":material/sync_alt: CDC", ":material/rule: Contrato",
    ":material/history: Viaje en el tiempo", ":material/build: Mantenimiento",
])

# ----------------------------------------------------------------- resumen

with tab_res:
    c, m = auditoria()
    h = cortes_oro()
    ultimo = h[h.dia_corte == h.dia_corte.max()]
    k = indicadores(ultimo, ["fecha_promesa"])
    k_mes = indicadores(ultimo.assign(mes=pd.to_datetime(ultimo.fecha_promesa).dt.to_period("M")), ["mes"])
    s = ST.set_index("tabla")
    cols = st.columns(5)
    cols[0].metric("Envíos en plata", f"{int(s.loc['plata.envios', 'filas']):,}")
    cols[1].metric("Eventos en bronce", f"{int(s.loc['bronce.cdc_envios', 'filas']):,}")
    cols[2].metric("Cambios de estado", f"{int(s.loc['plata.estados_envio', 'filas']):,}")
    cols[3].metric("En cuarentena", f"{int(s.loc['plata.cuarentena', 'filas']):,}")
    ok = c["sobran_en_plata"] == 0 and not c["columnas_distintas"] and \
        c["faltan_en_plata"] == c["faltan_explicados_por_cuarentena"]
    cols[4].metric("Conciliación", "cuadra" if ok else "no cuadra")
    st.markdown(f'<div class="nota">Contra el origen: <b>{c["origen"]:,}</b> envíos, <b>{c["faltan_en_plata"]}</b> '
                f'faltan en plata y los {c["faltan_explicados_por_cuarentena"]} tienen sus eventos en cuarentena; '
                f'<b>{c["sobran_en_plata"]}</b> sobran y <b>{sum(c["columnas_distintas"].values())}</b> tienen alguna '
                f'columna distinta.</div>', unsafe_allow_html=True)
    st.write("")
    izq, der = st.columns([1.7, 1])
    with izq:
        st.markdown("#### Cumplimiento de promesa (OTD) por día, último corte")
        k = k.sort_values("fecha_promesa")
        k["dia"] = dias(k.fecha_promesa)
        k["txt"] = k.otd.map(lambda x: f"{x:.1%}")
        base = alt.Chart(k).encode(x=eje_dias(list(k.dia)))
        linea = base.mark_line(color=ACENTO, strokeWidth=2).encode(
            y=alt.Y("otd:Q", title=None, scale=alt.Scale(zero=False, nice=True), axis=alt.Axis(format=".0%")),
            tooltip=[alt.Tooltip("dia:N", title="promesa"), alt.Tooltip("txt:N", title="OTD"),
                     alt.Tooltip("comprometidos:Q", format=",")])
        st.altair_chart((linea + base.mark_circle(color=ACENTO, size=18).encode(y="otd:Q")).properties(height=290),
                        width="stretch")
    with der:
        st.markdown("#### Por mes")
        v = k_mes.copy()
        v["mes"] = v.mes.map(lambda p: f"{MESES[p.month - 1]} {p.year}")
        v["otd"] *= 100
        v["primer_intento"] *= 100
        st.dataframe(v[["mes", "comprometidos", "otd", "primer_intento"]], hide_index=True,
                     width="stretch", column_config={
                         "comprometidos": st.column_config.NumberColumn(format="localized"),
                         "otd": st.column_config.NumberColumn("OTD", format="%.1f%%"),
                         "primer_intento": st.column_config.NumberColumn("1er intento", format="%.1f%%")})
        camp = k[(pd.to_datetime(k.fecha_promesa) >= "2026-07-15") & (pd.to_datetime(k.fecha_promesa) <= "2026-07-20")]
        st.markdown(f'<div class="nota">La campaña de ofertas (14 al 16 de julio) satura el reparto: las promesas '
                    f'del 15 al 20 de julio cierran con OTD de <b>{camp.a_tiempo.sum() / camp.comprometidos.sum():.1%}'
                    f'</b>.</div>', unsafe_allow_html=True)

    st.markdown("#### Tablas")
    vista = ST[["tabla", "filas", "archivos_datos", "mb_datos", "manifiestos", "snapshots", "kb_metadata_json",
                "marca"]].copy()
    vista["marca"] = vista.marca.map(lambda x: etiqueta_corte(x) if x else "")
    st.dataframe(vista, hide_index=True, width="stretch", column_config={
        "filas": st.column_config.NumberColumn(format="localized"), "archivos_datos": "archivos",
        "mb_datos": st.column_config.NumberColumn("MB", format="%.1f"),
        "kb_metadata_json": st.column_config.NumberColumn("metadata.json (KB)", format="%.0f"),
        "marca": "marca de agua"})

# ----------------------------------------------------------------- cdc

with tab_cdc:
    c, m = auditoria()
    tot = LOTES[["eventos", "duplicados", "tardios", "descartados_lsn", "borrados"]].sum()
    cols = st.columns(4)
    for col, (titulo, valor, nota) in zip(cols, [
            ("Duplicados", tot.duplicados, f"{tot.duplicados / tot.eventos:.2%} de los eventos"),
            ("Llegaron en un lote posterior", tot.tardios, f"{tot.tardios / tot.eventos:.2%} de los eventos"),
            ("Ignorados por lsn", tot.descartados_lsn, "más viejos que lo que ya estaba en plata"),
            ("Borrados aplicados", tot.borrados, "envíos de prueba del cliente QA")]):
        col.metric(titulo, f"{int(valor):,}")
        col.markdown(f'<div class="nota">{nota}</div>', unsafe_allow_html=True)
    st.write("")
    st.markdown("#### Eventos por día y qué se hizo con ellos")
    d = LOTES.assign(fecha=LOTES.lote.map(lambda x: corte_de(x).date())).groupby("fecha", as_index=False)[
        ["eventos", "duplicados", "tardios", "descartados_lsn"]].sum().sort_values("fecha")
    d["dia"] = dias(d.fecha)
    largo = d.melt(id_vars=["dia"], value_vars=["duplicados", "tardios", "descartados_lsn"], var_name="tipo",
                   value_name="n")
    largo["tipo"] = largo.tipo.map({"duplicados": "duplicados", "tardios": "tardíos",
                                    "descartados_lsn": "ignorados por lsn"})
    barras = alt.Chart(largo).mark_bar(width=4).encode(
        x=eje_dias(list(d.dia)), y=alt.Y("n:Q", title="eventos", stack=True),
        color=alt.Color("tipo:N", title=None, scale=alt.Scale(domain=["duplicados", "tardíos", "ignorados por lsn"],
                                                               range=[AMBAR, ACENTO, ROJO]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("dia:N", title="día"), "tipo:N", alt.Tooltip("n:Q", format=",")])
    st.altair_chart(barras.properties(height=260), width="stretch")
    pico = d.loc[d.duplicados.idxmax()]
    st.markdown(f'<div class="nota">Los picos de duplicados son reinicios del conector: reenvía las últimas dos horas '
                f'del lote anterior. El mayor fue el <b>{pico.dia}</b> con <b>{int(pico.duplicados):,}</b>. '
                f'Tardío no es lo mismo que ignorado: un evento que llega un lote tarde se aplica igual si nadie lo '
                f'pasó; se ignora solo si plata ya tiene un lsn mayor para ese envío.</div>', unsafe_allow_html=True)
    st.write("")
    st.markdown("#### Aplicar el CDC en el orden en que llega, sin mirar el lsn")
    st.markdown(
        f'<div class="lectura">a la mala: <span class="r">{m["estado_distinto"]:,}</span> envíos con el estado final '
        f'distinto al de origen · <span class="r">{m["entregados_que_no_figuran"]:,}</span> entregados que no figuran '
        f'como entregados<br>'
        f'con lsn y contrato: <span class="v">{m["plata_estado_distinto"]:,}</span> envíos con estado distinto</div>',
        unsafe_allow_html=True)
    cruce = m["cruce"].head(8).rename(columns={"en_origen": "en origen", "a_la_mala": "aplicando en orden de llegada"})
    st.dataframe(cruce, hide_index=True, width="stretch")

# ----------------------------------------------------------------- contrato

with tab_con:
    q = cuarentena().explode("violaciones")
    q["fecha"] = q.lote.map(lambda x: corte_de(x).date())
    if True:
        st.markdown("#### Eventos en cuarentena por día y regla")
        g = q.groupby(["fecha", "violaciones"], as_index=False).size()
        todas = pd.DataFrame({"fecha": sorted({corte_de(x).date() for x in LOTES.lote})})
        todas["dia"] = dias(todas.fecha)
        g = g.merge(todas, on="fecha")
        reglas = list(q.violaciones.value_counts().index)
        colores = [AMBAR, ROJO, ACENTO, VIOLETA, VERDE, GRIS][: len(reglas)]
        eje = list(todas.dia)
        st.altair_chart(alt.Chart(g).mark_bar(width=5).encode(
            x=alt.X("dia:O", title=None, scale=alt.Scale(domain=eje),
                    axis=alt.Axis(values=eje[::7], labelAngle=0, ticks=False)),
            y=alt.Y("size:Q", title="eventos", stack=None, scale=alt.Scale(type="log", domain=[1, 5000]),
                    axis=alt.Axis(values=[1, 10, 100, 1000], format="~s")),
            color=alt.Color("violaciones:N", title=None, scale=alt.Scale(domain=reglas, range=colores),
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("dia:N", title="día"), alt.Tooltip("violaciones:N", title="regla"),
                     alt.Tooltip("size:Q", title="eventos", format=",")]).properties(height=260), width="stretch")
        st.markdown('<div class="nota">Eje en escala logarítmica: el incidente de mayúsculas deja miles de eventos en '
                    'seis horas y las erratas de distrito, uno o dos por día.</div>', unsafe_allow_html=True)
    izq, der = st.columns([1.4, 1])
    with izq:
        st.markdown("#### Por regla")
        r = q.groupby("violaciones").agg(eventos=("lsn", "size"), envios=("id_envio", "nunique"),
                                         desde=("lote", "min"), hasta=("lote", "max")).sort_values("eventos",
                                                                                                   ascending=False)
        r = r.reset_index()
        r["desde"] = r.desde.map(etiqueta_corte)
        r["hasta"] = r.hasta.map(etiqueta_corte)
        st.dataframe(r, hide_index=True, width="stretch", column_config={
            "violaciones": "regla", "eventos": st.column_config.NumberColumn(format="localized"),
            "envios": st.column_config.NumberColumn("envíos", format="localized")})
    with der:
        st.write("")
        c, _ = auditoria()
        st.markdown(f'<div class="nota">Al final del periodo faltan en plata <b>{c["faltan_en_plata"]}</b> envíos que '
                    f'sí están en origen. Todos tienen sus eventos en cuarentena por distrito mal escrito: nadie lo '
                    f'corrigió en origen. Los del peso en gramos y los estados en mayúsculas se recuperaron solos '
                    f'cuando llegó el UPDATE de corrección.</div>', unsafe_allow_html=True)
    st.write("")
    st.markdown("#### Lotes sobre el umbral del contrato")
    lt = LOTES.copy()
    lt["tasa"] = lt.cuarentena / (lt.eventos - lt.duplicados).clip(lower=1)
    alto = lt[lt.tasa > CONTRATO.umbral_cuarentena][["lote", "eventos", "cuarentena", "tasa"]].copy()
    alto["lote"] = alto.lote.map(etiqueta_corte)
    alto["tasa"] *= 100
    st.dataframe(alto, hide_index=True, width="stretch", height=250, column_config={
        "eventos": st.column_config.NumberColumn(format="localized"),
        "tasa": st.column_config.NumberColumn("% del lote", format="%.1f%%")})
    evol = LOTES[(LOTES.columnas_nuevas != "") | (LOTES.no_declaradas != "")]
    if len(evol):
        primero, cambio = evol.iloc[0], evol[evol.columnas_nuevas != ""]
        st.markdown(
            f'<div class="lectura">esquema · <span class="a">{primero.no_declaradas}</span> aparece en origen en el '
            f'lote {etiqueta_corte(primero.lote)}: fuera del contrato, queda solo en bronce'
            + (f'<br>{etiqueta_corte(cambio.iloc[0].lote)} · rige v{cambio.iloc[0].version_contrato}: plata agrega la '
               f'columna y rellena <span class="c">{int(cambio.iloc[0].rellenados):,}</span> envíos con el evento '
               f'que guardó bronce' if len(cambio) else "") + '</div>', unsafe_allow_html=True)
    with st.expander("contratos/envios.yml", icon=":material/description:"):
        st.code(ruta_contrato().read_text(encoding="utf-8"), language="yaml")

# ----------------------------------------------------------------- viaje en el tiempo

with tab_viaje:
    h = cortes_oro()
    fechas = sorted(pd.to_datetime(h.fecha_promesa).dt.date.unique())
    c1, c2 = st.columns([1, 2.4])
    comp_total = reportado_vs_final(h)
    peor = pd.Timestamp(comp_total.loc[comp_total.brecha_pp.idxmax(), "fecha_promesa"]).date()
    elegida = c1.selectbox("Promesas del día", fechas, index=fechas.index(peor),
                           format_func=lambda d: etiqueta_dia(d, True),
                           help="Por defecto, el día en que el tablero de la mañana más se equivocó.")
    zona = c1.radio("Zona", ["todas", "lima_centro", "lima_periferia", "callao", "provincia"])
    sel = h[pd.to_datetime(h.fecha_promesa).dt.date == elegida]
    if zona != "todas":
        sel = sel[sel.zona == zona]
    serie = indicadores(sel, ["dia_corte"]).sort_values("dia_corte").head(10)
    serie["dia"] = dias(serie.dia_corte)
    serie["txt"] = serie.otd.map(lambda x: f"{x:.1%}")
    base = alt.Chart(serie).encode(x=alt.X("dia:O", sort=list(serie.dia), title="corte de las 06:00",
                                           axis=alt.Axis(labelAngle=0)))
    graf = base.mark_line(color=ACENTO, strokeWidth=2.4, interpolate="step-after").encode(
        y=alt.Y("otd:Q", title=None, scale=alt.Scale(zero=False, nice=True), axis=alt.Axis(format=".1%")),
        tooltip=[alt.Tooltip("dia:N", title="corte"), alt.Tooltip("txt:N", title="OTD"),
                 alt.Tooltip("pendientes:Q", title="pendientes")])
    with c2:
        st.altair_chart((graf + base.mark_circle(color=ACENTO, size=60).encode(y="otd:Q")).properties(height=280),
                        width="stretch")
    if len(serie) > 1:
        donde = "" if zona == "todas" else " · " + zona
        st.markdown(f'<div class="lectura">promesas del {etiqueta_dia(elegida, True)}{donde}: '
                    f'la mañana siguiente el tablero dijo <span class="a">{serie.otd.iloc[0]:.1%}</span> · '
                    f'último corte <span class="c">{serie.otd.iloc[-1]:.1%}</span> · '
                    f'{int(serie.a_tiempo.iloc[-1] - serie.a_tiempo.iloc[0])} entregas a tiempo que se sincronizaron '
                    f'después del corte</div>', unsafe_allow_html=True)

    st.markdown("#### Cuánto se equivoca el OTD de la mañana siguiente, por zona")
    comp = reportado_vs_final(h, ["zona"])
    comp = comp[comp.comprometidos_final >= 20]
    resumen = comp.groupby("zona").agg(dias=("brecha_pp", "size"), brecha_media=("brecha_pp", "mean"),
                                       brecha_p90=("brecha_pp", lambda x: x.quantile(0.9)),
                                       brecha_max=("brecha_pp", "max")).reset_index()
    st.dataframe(resumen.sort_values("brecha_media", ascending=False), hide_index=True, width="stretch",
                 column_config={"dias": "días",
                                "brecha_media": st.column_config.NumberColumn("brecha media (pp)", format="%.2f"),
                                "brecha_p90": st.column_config.NumberColumn("p90 (pp)", format="%.2f"),
                                "brecha_max": st.column_config.NumberColumn("máxima (pp)", format="%.2f")})
    st.markdown('<div class="nota">Brecha = OTD del último corte menos OTD reportado la mañana siguiente. '
                'Cada corte es '
                'un tag de Iceberg (<b>corte-AAAA-MM-DD</b>) sobre un snapshot de oro; expirar snapshots no los '
                'borra.</div>', unsafe_allow_html=True)

# ----------------------------------------------------------------- mantenimiento

with tab_mant:
    if MANT.empty:
        st.info("Todavía no corrió el mantenimiento.", icon=":material/info:")
    else:
        ultimo = MANT[MANT.lote == MANT.lote.max()]
        cols = st.columns(4)
        b = MANT[MANT.tabla == "bronce"]
        cols[0].metric("Corridas de mantenimiento", f"{MANT.lote.nunique()}")
        cols[1].metric("Archivos compactados", f"{int(MANT.archivos_compactados.sum()):,}")
        cols[2].metric("Snapshots expirados", f"{int(MANT.snapshots_expirados.sum()):,}")
        cols[3].metric("Huérfanos borrados", f"{int(MANT.huerfanos_borrados.sum()):,}")
        st.write("")
        izq, der = st.columns(2)
        with izq:
            st.markdown("#### Lectura completa de bronce, antes y después de compactar")
            b = b.assign(fecha=b.lote.map(lambda x: corte_de(x).date())).sort_values("fecha")
            b["dia"] = dias(b.fecha)
            lb = b.melt(id_vars=["dia"], value_vars=["antes_seg_lectura", "despues_seg_lectura"], var_name="momento",
                        value_name="seg")
            lb["momento"] = lb.momento.map({"antes_seg_lectura": "antes", "despues_seg_lectura": "después"})
            st.altair_chart(alt.Chart(lb).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("dia:O", sort=list(b.dia), title="domingo", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("seg:Q", title="segundos", scale=alt.Scale(zero=False)),
                color=alt.Color("momento:N", title=None, scale=alt.Scale(domain=["antes", "después"],
                                                                         range=[AMBAR, ACENTO]),
                                legend=alt.Legend(orient="top")),
                tooltip=["dia:N", "momento:N", alt.Tooltip("seg:Q", format=".2f")]).properties(height=260),
                width="stretch")
        with der:
            st.markdown("#### Segundos por lote en la ingesta")
            lt = LOTES.copy()
            lt["seg"] = lt[[c for c in lt.columns if c.startswith("seg_") and c != "seg_mantenimiento"]].sum(axis=1)
            lt = lt.assign(fecha=lt.lote.map(lambda x: corte_de(x).date())).groupby("fecha", as_index=False).seg.mean()
            lt["dia"] = dias(lt.fecha)
            st.altair_chart(alt.Chart(lt).mark_line(color=ACENTO, strokeWidth=1.6).encode(
                x=eje_dias(list(lt.dia), 14), y=alt.Y("seg:Q", title="segundos (promedio del día)",
                                                       scale=alt.Scale(zero=False)),
                tooltip=["dia:N", alt.Tooltip("seg:Q", format=".2f")]).properties(height=260), width="stretch")
        st.markdown(f"#### Último mantenimiento · {etiqueta_corte(ultimo.lote.iloc[0])}")
        v = ultimo.copy()
        v["tabla"] = v.tabla.map(NOMBRES)
        v["archivos"] = v.antes_archivos_datos.astype(str) + " → " + v.despues_archivos_datos.astype(str)
        v["snapshots"] = v.antes_snapshots.astype(str) + " → " + v.despues_snapshots.astype(str)
        v["en_disco"] = v.antes_archivos_en_disco.astype(str) + " → " + v.despues_archivos_en_disco.astype(str)
        v["metadata"] = v.antes_kb_metadata_json.map("{:.0f}".format) + " → " + \
            v.despues_kb_metadata_json.map("{:.0f}".format) + " KB"
        st.dataframe(v[["tabla", "archivos", "snapshots", "en_disco", "metadata", "huerfanos_borrados", "segundos"]],
                     hide_index=True, width="stretch", column_config={
                         "en_disco": "archivos en disco", "metadata": "metadata.json",
                         "huerfanos_borrados": "huérfanos borrados",
                         "segundos": st.column_config.NumberColumn(format="%.1f")})
