"""
Interfaz del asistente: preguntar con fecha de consulta, ver los artículos que
sustentan la respuesta y revisar la evaluación.

    streamlit run app.py
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from reglamento.cli import cargar_env, crear_asistente  # noqa: E402
from reglamento.corpus import cargar_corpus  # noqa: E402
from reglamento.evaluacion import FECHA_EVALUACION  # noqa: E402
from reglamento.llm import MODELO_DEFECTO  # noqa: E402
from reglamento.rutas import ruta_corpus, ruta_resultados  # noqa: E402

cargar_env()
st.set_page_config(page_title="reglamento · Qhapaq Ñan", page_icon=":material/gavel:", layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
[data-testid="stMetric"] { border: 1px solid #1F2A36; border-radius: 8px; padding: 12px 16px; background: #0F151C; }
[data-testid="stSidebar"] button p { font-size: .82rem; text-align: left; }
[data-testid="stSidebar"] button { justify-content: flex-start; border-color: #1F2A36; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.estado { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #7D8B99;
          border: 1px solid #1F2A36; border-radius: 6px; padding: 6px 10px; display: inline-block; }
.estado b { color: #34D399; font-weight: 600; }
.pregunta { font-size: .95rem; color: #9AA7B4; margin: .2rem 0 .4rem 0; }
.pregunta b { color: #D6DEE6; font-weight: 500; }
.respuesta { border: 1px solid #1F2A36; border-left: 3px solid #34D399; border-radius: 8px; padding: 14px 18px;
             background: #0F151C; color: #D6DEE6; font-size: 1rem; line-height: 1.55; margin-bottom: .6rem; }
.respuesta.no { border-left-color: #FBBF24; }
.cita { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #22D3EE; border: 1px solid #164E5A;
        border-radius: 4px; padding: 2px 8px; margin-right: 6px; background: #0B1A20; }
.nota { font-size: .85rem; color: #9AA7B4; }
.nota b { color: #D6DEE6; font-family: 'JetBrains Mono', monospace; font-weight: 600; }
.articulo { border: 1px solid #1F2A36; border-radius: 8px; padding: 10px 14px; background: #0F151C; margin-bottom: 8px; }
.articulo .t { font-family: 'JetBrains Mono', monospace; font-size: .8rem; color: #7D8B99; }
.articulo .t b { color: #D6DEE6; font-weight: 600; }
.articulo .v { color: #34D399; } .articulo .d { color: #F87171; }
.articulo p { margin: .35rem 0 0 0; font-size: .9rem; color: #C3CDD6; }
h4 { font-weight: 600 !important; font-size: 1rem !important; color: #D6DEE6; margin-top: .4rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO, GRIS, GRIS_OSCURO = "#22D3EE", "#7D8B99", "#46535F"
VERDE, AMBAR, ROJO = "#34D399", "#FBBF24", "#F87171"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
HAY_KEY = bool(os.getenv("LLM_API_KEY"))
EJEMPLOS = [
    "hasta cuando me puedo retirar de un curso que voy jalando?",
    "si jalo un curso por cuarta vez me botan?",
    "puedo usar chatgpt para hacer mis trabajos?",
    "quiero congelar un ciclo para chambear, por cuanto tiempo puedo?",
    "si debo pensiones me pueden prohibir dar el examen final?",
    "cuanto de turnitin me aceptan en la tesis?",
    "¿A qué hora abre la biblioteca los sábados?",
]


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


def fecha_corta(d: date) -> str:
    """'1 mar 2026', armado en Python para no depender de la configuración regional."""
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


if not ruta_corpus().exists():
    st.error("Falta el corpus.", icon=":material/folder_off:")
    st.code("python -m reglamento todo", language="bash")
    st.stop()


@st.cache_resource(show_spinner="Cargando el modelo de vectores...")
def asistente(demo: bool, sin_vectores: bool):
    return crear_asistente(demo, sin_vectores)


@st.cache_data(show_spinner=False)
def corpus():
    return cargar_corpus(ruta_corpus())


@st.cache_data(show_spinner=False)
def evaluacion():
    ruta = ruta_resultados() / "resumen.json"
    if not ruta.exists():
        return None, None
    return (json.loads(ruta.read_text(encoding="utf-8")),
            pd.read_csv(ruta_resultados() / "busqueda.csv"))


FRAGMENTOS = corpus()
RESUMEN, DETALLE = evaluacion()

# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Universidad Qhapaq Ñan")
    st.caption("6 normas · 72 artículos · universidad ficticia, datos sintéticos")

    modo = st.radio("Redacción", ["LLM (API)", "Extractiva, sin API key"], index=0 if HAY_KEY else 1,
                    disabled=not HAY_KEY, help="Sin LLM_API_KEY la respuesta es el artículo recuperado, tal cual.")
    demo = modo.startswith("Extractiva")
    sin_vectores = st.toggle("Solo BM25 (sin modelo de vectores)", value=False,
                             help="Usa BM25 con diccionario de jerga; no descarga el modelo de ~2.2 GB.")
    fecha = st.date_input("Fecha de la consulta", value=FECHA_EVALUACION, format="DD/MM/YYYY",
                          min_value=date(2024, 3, 1), max_value=date(2027, 12, 31),
                          help="Decide qué versión de cada artículo está vigente.")

    st.subheader("Preguntas de ejemplo")
    for i, ej in enumerate(EJEMPLOS):
        if st.button(ej, key=f"ej{i}", width="stretch"):
            st.session_state.pregunta = ej

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> reglamento</p>', unsafe_allow_html=True)
st.caption("Preguntas de estudiantes sobre las normas académicas. Busca el artículo vigente a la fecha, "
           "decide si hay con qué responder y cita cada fuente.")

try:
    AS = asistente(demo, sin_vectores)
except Exception as e:  # sin red para bajar el modelo, por ejemplo
    st.error(f"No se pudo cargar el asistente: {e}", icon=":material/error:")
    st.stop()

vectores = AS.recuperador.codificador.nombre.split("/")[-1] if AS.recuperador.codificador else "sin vectores"
st.markdown(
    f'<div class="estado"><b>●</b> {len(FRAGMENTOS)} fragmentos · búsqueda: {AS.config.nombre} · {vectores} · '
    f'umbral {AS.umbral:.3f} · redacción: {"extractiva" if demo else os.getenv("LLM_MODELO", MODELO_DEFECTO)}'
    f'</div>', unsafe_allow_html=True)
st.write("")

tab_preguntar, tab_eval, tab_normas = st.tabs([":material/forum: Preguntar", ":material/analytics: Evaluación",
                                               ":material/gavel: Normas"])

# ----------------------------------------------------------------- preguntar

with tab_preguntar:
    with st.form("form_pregunta", border=False):
        c1, c2 = st.columns([6, 1], vertical_alignment="bottom")
        texto = c1.text_input("Pregunta", value=st.session_state.get("pregunta", ""),
                              placeholder="Ej: hasta cuando puedo retirarme de un curso?",
                              label_visibility="collapsed")
        enviar = c2.form_submit_button("Preguntar", icon=":material/search:", width="stretch")
    pregunta = texto.strip() if (enviar or st.session_state.get("pregunta")) else ""

    if pregunta:
        r = AS.preguntar(pregunta, fecha)
        st.markdown(f'<p class="pregunta">Consulta del {fecha_corta(fecha)}: <b>{html.escape(pregunta)}</b></p>',
                    unsafe_allow_html=True)
        clase = "respuesta" if r.respondio else "respuesta no"
        st.markdown(f'<div class="{clase}">{html.escape(r.texto)}</div>', unsafe_allow_html=True)
        if r.citas:
            st.markdown("".join(f'<span class="cita">{html.escape(f.cita)}</span>' for f in r.citas),
                        unsafe_allow_html=True)
        st.write("")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Confianza", f"{r.busqueda.confianza:.3f}",
                  help="Coseno del artículo más parecido; con BM25 solo, el puntaje BM25.")
        m2.metric("Umbral", f"{AS.umbral:.3f}")
        m3.metric("Resultado", "responde" if r.respondio else "abstiene",
                  help=None if r.respondio else f"Motivo: {r.abstencion}")
        m4.metric("Tiempo", f"{r.segundos:.2f} s")

        # versiones anteriores de los artículos citados
        for f in r.citas:
            previos = [p for p in FRAGMENTOS if p.documento == f.documento and p.articulo == f.articulo
                       and p.id != f.id and p.vigente_hasta and p.vigente_hasta < fecha]
            for p in previos:
                st.info(f"El artículo {f.articulo} del {f.documento} fue modificado por {f.fuente}, vigente desde "
                        f"el {fecha_corta(f.vigente_desde)}. La versión anterior decía: «{p.texto}»",
                        icon=":material/history:")

        st.markdown("#### Artículos recuperados")
        filas = pd.DataFrame([{
            "pos": i, "articulo": res.fragmento.cita, "titulo": res.fragmento.titulo,
            "puntaje": res.coseno if res.coseno is not None else res.bm25,
            "citado": "citado" if res.fragmento in r.citas else "no citado",
        } for i, res in enumerate(r.busqueda.resultados, 1)])
        etiqueta = "coseno" if r.busqueda.resultados[0].coseno is not None else "bm25"
        orden = list(filas["articulo"])
        # las barras parten del borde izquierdo del dominio: se acota para que las diferencias se vean
        valores = list(filas["puntaje"]) + ([AS.umbral] if etiqueta == "coseno" else [])
        margen = 0.15 * (max(valores) - min(valores) or 1)
        dominio = [min(valores) - margen, max(valores) + margen / 3] if etiqueta == "coseno" else [0, max(valores) * 1.05]
        barras = alt.Chart(filas).mark_bar(cornerRadiusEnd=3, height=16).encode(
            y=alt.Y("articulo:N", sort=orden, title=None, axis=alt.Axis(labelFont="JetBrains Mono", labelLimit=320)),
            x=alt.X("puntaje:Q", title=etiqueta, scale=alt.Scale(domain=dominio, clamp=True)),
            color=alt.Color("citado:N", scale=alt.Scale(domain=["citado", "no citado"], range=[ACENTO, GRIS_OSCURO]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["articulo", "titulo", alt.Tooltip("puntaje:Q", format=".3f")],
        )
        capas = barras
        if etiqueta == "coseno":
            capas = barras + alt.Chart(pd.DataFrame({"u": [AS.umbral]})).mark_rule(
                color=AMBAR, strokeDash=[4, 3]).encode(x="u:Q")
        st.altair_chart(capas.properties(height=40 * len(filas) + 30), width="stretch")
        if etiqueta == "coseno":
            st.caption("La línea ámbar es el umbral de abstención: si el mejor artículo queda a la izquierda, "
                       "el asistente no responde.")

        for res in r.busqueda.resultados:
            f = res.fragmento
            mod = f" · <span class='v'>vigente desde {fecha_corta(f.vigente_desde)}</span>" if f.fuente != f.documento else ""
            st.markdown(
                f'<div class="articulo"><div class="t"><b>{html.escape(f.titulo_documento)}</b> · art. {f.articulo} · '
                f'{html.escape(f.titulo)}{mod}</div><p>{html.escape(f.texto)}</p></div>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="nota">Escribe una pregunta o elige un ejemplo. Prueba la misma pregunta con '
                    'fecha <b>01/10/2025</b> y <b>01/09/2026</b>: entre ambas rige la Resolución 014-2026-CU.</p>',
                    unsafe_allow_html=True)

# ----------------------------------------------------------------- evaluación

with tab_eval:
    if RESUMEN is None:
        st.info("Todavía no hay evaluación.", icon=":material/info:")
        st.code("python -m reglamento evaluar", language="bash")
    else:
        reg = pd.DataFrame(RESUMEN["busqueda_por_registro"])
        tot = pd.DataFrame(RESUMEN["busqueda"])
        tot = tot[tot["split"] == "prueba"]
        clave = RESUMEN["respuestas_extractivo"]["config"]
        u = RESUMEN["umbrales"][clave]
        defecto = clave.split(" · ")[0]
        errores = {e["config"]: e for e in RESUMEN["errores_version"]}

        st.markdown(f'<p class="nota">Preguntas de <b>prueba</b> ({int(tot["n"].iloc[0])} con respuesta y '
                    f'{u["sin_respuesta"]} sin respuesta), fecha de consulta <b>{RESUMEN["fecha_evaluacion"]}</b>. '
                    f'La configuración y el umbral se eligieron con las de desarrollo.</p>', unsafe_allow_html=True)
        k1, k2, k3, k4 = st.columns(4)
        fila = reg[(reg["config"] == defecto) & (reg["registro"] == "coloquial")].iloc[0]
        k1.metric("Acierto@1 coloquial", f"{100 * fila['acierto@1']:.1f}%")
        k2.metric("Acierto@5", f"{100 * tot.set_index('config').loc[defecto, 'acierto@5']:.1f}%")
        k3.metric("Sin respuesta detectadas", f"{u['sin_respuesta_abstenidas']} de {u['sin_respuesta']}")
        sv = errores.get("vectorial sin vigencia", errores.get(defecto))
        k4.metric("Derogado primero sin vigencia", f"{sv['errores']} de {sv['n']}")

        st.markdown("#### Acierto@1 por configuración y registro")
        orden_cfg = list(tot["config"])
        graf = alt.Chart(reg).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("config:N", sort=orden_cfg, title=None, axis=alt.Axis(labelFont="JetBrains Mono", labelLimit=260)),
            yOffset=alt.YOffset("registro:N", sort=["formal", "coloquial"]),
            x=alt.X("acierto@1:Q", title="acierto@1", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("registro:N", scale=alt.Scale(domain=["formal", "coloquial"], range=[GRIS, ACENTO]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["config", "registro", alt.Tooltip("acierto@1:Q", format=".1%"), "n"],
        )
        texto_barras = graf.mark_text(align="left", dx=4, font="JetBrains Mono", fontSize=10, color="#9AA7B4").encode(
            text=alt.Text("acierto@1:Q", format=".0%"))
        st.altair_chart((graf + texto_barras).properties(height=330), width="stretch")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("#### Confianza: preguntas con y sin respuesta")
            d = DETALLE[(DETALLE["config"] == defecto) & (DETALLE["split"] == "prueba")].copy()
            d["grupo"] = d["con_respuesta"].map({True: "con respuesta", False: "sin respuesta"})
            puntos = alt.Chart(d).mark_tick(thickness=2, size=22).encode(
                x=alt.X("confianza:Q", title="coseno del mejor artículo", scale=alt.Scale(zero=False, nice=True)),
                y=alt.Y("grupo:N", title=None),
                color=alt.Color("grupo:N", scale=alt.Scale(domain=["con respuesta", "sin respuesta"],
                                                           range=[ACENTO, AMBAR]), legend=None),
                tooltip=["pregunta", alt.Tooltip("confianza:Q", format=".3f")],
            )
            regla = alt.Chart(pd.DataFrame({"u": [u["umbral"]]})).mark_rule(color=ROJO, strokeDash=[4, 3]).encode(x="u:Q")
            st.altair_chart((puntos + regla).properties(height=170), width="stretch")
            st.caption(f"Umbral {u['umbral']:.3f} (línea roja), fijado para dejar pasar 95% de las preguntas válidas "
                       f"de desarrollo. AUC en prueba: {u['auc']}.")
            if u["ajenas_que_pasan"]:
                st.markdown('<p class="nota">Sin respuesta que igual pasan el umbral: ' +
                            " · ".join(f"<i>{html.escape(q)}</i>" for q in u["ajenas_que_pasan"]) + "</p>",
                            unsafe_allow_html=True)
        with c2:
            st.markdown("#### Modelos de vectores")
            if "modelos" in RESUMEN:
                m = pd.DataFrame(RESUMEN["modelos"])
                m["modelo"] = m["modelo"].str.split("/").str[-1].str.replace("paraphrase-multilingual-", "")
                st.dataframe(m[["modelo", "acierto@1 formal", "acierto@1 coloquial", "auc", "ms_por_pregunta"]],
                             hide_index=True, width="stretch", column_config={
                                 "acierto@1 formal": st.column_config.NumberColumn(format="percent"),
                                 "acierto@1 coloquial": st.column_config.NumberColumn(format="percent"),
                                 "auc": st.column_config.NumberColumn("AUC", format="%.3f"),
                                 "ms_por_pregunta": st.column_config.NumberColumn("ms/pregunta", format="%.0f")})
                st.caption("Búsqueda solo vectorial, preguntas de prueba, CPU.")
            else:
                st.caption("Corre `python -m reglamento evaluar --modelos` para comparar.")

        st.markdown("#### Dónde falla la configuración por defecto")
        fallas = DETALLE[(DETALLE["config"] == defecto) & (DETALLE["split"] == "prueba") &
                         DETALLE["con_respuesta"] & (DETALLE["posicion"] != 1)]
        fallas = fallas.assign(posicion=fallas["posicion"].map(lambda x: "fuera del top 5" if pd.isna(x) else f"{int(x)}"))
        st.dataframe(fallas[["pregunta", "registro", "gold", "top1", "posicion"]], hide_index=True, width="stretch",
                     column_config={"gold": "esperado", "top1": "primer resultado",
                                    "posicion": "posición del esperado"})

# ----------------------------------------------------------------- normas

with tab_normas:
    documentos = sorted({(f.documento, f.titulo_documento) for f in FRAGMENTOS})
    inicial = next((i for i, d in enumerate(documentos) if d[0] == "RE-2024"), 0)
    elegido = st.selectbox("Norma", documentos, index=inicial, format_func=lambda d: f"{d[0]} · {d[1]}")
    for f in sorted([f for f in FRAGMENTOS if f.documento == elegido[0]],
                    key=lambda f: (int(f.articulo.split("-")[0]), f.articulo, f.vigente_desde)):
        if f.vigente_hasta:
            estado = f"<span class='d'>vigente hasta {fecha_corta(f.vigente_hasta)}</span>"
        elif f.fuente != f.documento:
            estado = f"<span class='v'>{f.fuente} · vigente desde {fecha_corta(f.vigente_desde)}</span>"
        else:
            estado = f"vigente desde {fecha_corta(f.vigente_desde)}"
        st.markdown(
            f'<div class="articulo"><div class="t"><b>art. {f.articulo} · {html.escape(f.titulo)}</b> · {estado}</div>'
            f'<p>{html.escape(f.texto)}</p></div>', unsafe_allow_html=True)
