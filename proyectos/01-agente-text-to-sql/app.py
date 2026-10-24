"""
Interfaz web del agente.

    streamlit run app.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import sqlglot
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from text2sql.cli import cargar_env, crear_agente  # noqa: E402
from text2sql.db import _a_json  # noqa: E402
from text2sql.llm import MODELO_DEFECTO  # noqa: E402

cargar_env()
st.set_page_config(page_title="text2sql · La Esquina", page_icon=":material/database:", layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
[data-testid="stSidebar"] button p { font-size: .82rem; text-align: left; }
[data-testid="stSidebar"] button { justify-content: flex-start; border-color: #1F2A36; }
[data-testid="stChatMessage"] { border: 1px solid #1F2A36; border-radius: 10px; background: #0F151C; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.estado { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #7D8B99;
          border: 1px solid #1F2A36; border-radius: 6px; padding: 6px 10px; display: inline-block; }
.estado b { color: #34D399; font-weight: 600; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

RUTA_DB = Path(os.getenv("TEXT2SQL_DB", RAIZ / "datos" / "minimarkets.duckdb"))
CASOS = json.loads((RAIZ / "evals" / "casos.json").read_text(encoding="utf-8"))
HAY_KEY = bool(os.getenv("LLM_API_KEY"))
AVATAR_USUARIO = ":material/person:"
AVATAR_AGENTE = ":material/terminal:"
ACENTO = "#22D3EE"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


@st.cache_resource(show_spinner=False)
def obtener_agente(demo: bool):
    return crear_agente(demo, RUTA_DB)


def grafico_sugerido(df: pd.DataFrame) -> None:
    """Si el resultado es 'una dimensión + una métrica', lo grafica."""
    if len(df) < 2 or len(df.columns) != 2:
        return
    dim, met = df.columns
    if not pd.api.types.is_numeric_dtype(df[met]):
        return
    datos = df.copy()
    temporal = any(x in dim.lower() for x in ("mes", "fecha", "dia", "semana"))
    if temporal:
        datos[dim] = pd.to_datetime(datos[dim], errors="coerce")
        temporal = datos[dim].notna().all()

    if temporal:
        # en series de tiempo el eje no arranca en cero: interesa la tendencia
        # etiquetas armadas en Python: evita que el navegador corra las fechas por zona horaria
        datos = datos.sort_values(dim)
        mensual = (datos[dim].dt.day == 1).all()
        datos["periodo"] = [
            f"{MESES[d.month - 1]} {d.year}" if mensual else d.strftime("%d/%m/%Y")
            for d in datos[dim]
        ]
        base = alt.Chart(datos).encode(
            x=alt.X("periodo:O", title=None, sort=list(datos["periodo"]),
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{met}:Q", title=met, scale=alt.Scale(zero=False, nice=True)),
            tooltip=["periodo", alt.Tooltip(f"{met}:Q", format=",.2f")],
        )
        grafico = base.mark_line(color=ACENTO, strokeWidth=2.5) + \
            base.mark_circle(color=ACENTO, size=60)
    else:
        grafico = alt.Chart(datos).mark_bar(color=ACENTO, cornerRadiusEnd=3).encode(
            y=alt.Y(f"{dim}:N", title=None, sort="-x"),
            x=alt.X(f"{met}:Q", title=met),
            tooltip=[dim, alt.Tooltip(f"{met}:Q", format=",.2f")],
        )
    st.altair_chart(grafico.properties(height=320), width="stretch")


def sql_legible(sql: str) -> str:
    try:
        return sqlglot.transpile(sql, read="duckdb", pretty=True)[0]
    except sqlglot.errors.ParseError:
        return sql


def mostrar_resultado(res, n: int) -> None:
    st.markdown(res.respuesta or "_Sin respuesta._")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pasos", len(res.pasos))
    c2.metric("Consultas corregidas", res.consultas_fallidas)
    c3.metric("Tokens", f"{res.tokens_entrada + res.tokens_salida:,}")
    c4.metric("Tiempo", f"{res.segundos:.1f} s")

    tab_datos, tab_sql, tab_pasos = st.tabs([":material/table: Resultado", ":material/code: SQL",
                                         ":material/account_tree: Traza"])
    with tab_datos:
        if res.filas:
            df = pd.DataFrame([[_a_json(v) for v in f] for f in res.filas], columns=res.columnas)
            df = df.round(2)
            formato = {c: st.column_config.NumberColumn(format="localized")
                       for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
                       and not any(x in c.lower() for x in ("id_", "anio", "año", "hora"))}
            st.dataframe(df, width="stretch", hide_index=True, column_config=formato)
            grafico_sugerido(df)
            st.download_button("Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                               "resultado.csv", "text/csv", key=f"csv_{n}")
        else:
            st.caption("La respuesta no tiene tabla asociada.")
    with tab_sql:
        st.code(res.sql or "-- sin SQL", language="sql")
    with tab_pasos:
        for i, p in enumerate(res.pasos, 1):
            icono = ":material/error:" if p.error else ":material/check_circle:"
            with st.expander(f"{i:02d} · {p.herramienta}", icon=icono):
                if p.pensamiento:
                    st.caption(p.pensamiento)
                if "sql" in p.entrada:
                    st.code(sql_legible(p.entrada["sql"]), language="sql")
                elif p.entrada:
                    st.json(p.entrada)
                st.text(p.salida[:2000])


# ----------------------------------------------------------------- barra lateral

with st.sidebar:
    st.subheader("Minimarkets La Esquina")
    st.caption("24 tiendas · ene 2025 – set 2026 · datos sintéticos")

    modo = st.radio(
        "Modo",
        ["LLM (API)", "Demo sin API key"],
        index=0 if HAY_KEY else 1,
        disabled=not HAY_KEY,
        help="Sin LLM_API_KEY solo funciona el modo demo.",
    )
    demo = modo.startswith("Demo")
    if demo:
        st.info("En modo demo solo responde las preguntas de ejemplo.", icon=":material/info:")

    st.subheader("Preguntas de ejemplo")
    for caso in CASOS:
        if st.button(caso["pregunta"], key=caso["id"], width="stretch"):
            st.session_state.pregunta_pendiente = caso["pregunta"]

    if st.button("Limpiar conversación", type="secondary"):
        st.session_state.historial = []


# ----------------------------------------------------------------- conversación

st.markdown('<p class="encabezado"><span>&gt;</span> text2sql</p>', unsafe_allow_html=True)
st.caption("Pregunta en español. El agente revisa el esquema, escribe el SQL, lo valida, "
           "lo ejecuta y responde con la consulta que sustenta cada cifra.")
st.markdown(
    f'<div class="estado"><b>●</b> duckdb · {RUTA_DB.name} · solo lectura · '
    f'modelo: {"demo" if demo else os.getenv("LLM_MODELO", MODELO_DEFECTO)}</div>',
    unsafe_allow_html=True,
)
st.write("")

st.session_state.setdefault("historial", [])

for n, (pregunta, res) in enumerate(st.session_state.historial):
    with st.chat_message("user", avatar=AVATAR_USUARIO):
        st.write(pregunta)
    with st.chat_message("assistant", avatar=AVATAR_AGENTE):
        mostrar_resultado(res, n)

pregunta = st.chat_input("Ej: ¿Cuánto vendimos con Yape en Miraflores en julio?")
pregunta = pregunta or st.session_state.pop("pregunta_pendiente", None)

if pregunta:
    with st.chat_message("user", avatar=AVATAR_USUARIO):
        st.write(pregunta)
    with st.chat_message("assistant", avatar=AVATAR_AGENTE):
        with st.spinner("Revisando la base..."):
            try:
                res = obtener_agente(demo).preguntar(pregunta)
            except Exception as e:  # se muestra el error en vez de romper la app
                st.error(f"Algo falló: {e}")
                st.stop()
        mostrar_resultado(res, len(st.session_state.historial))
    st.session_state.historial.append((pregunta, res))
