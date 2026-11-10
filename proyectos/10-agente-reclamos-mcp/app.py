"""
Tablero del agente de reclamos.

    streamlit run app.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from reclamos.cli import cargar_env, crear_agente  # noqa: E402
from reclamos.llm import MODELO_DEFECTO  # noqa: E402
from reclamos.permisos import PERFILES  # noqa: E402
from reclamos.rutas import ruta_db, ruta_resultados  # noqa: E402
from reclamos.servidor import Operaciones, Sistemas, crear_servidor  # noqa: E402

cargar_env()
st.set_page_config(page_title="Reclamos · Killa", page_icon=":material/support_agent:", layout="wide")

ACENTO, GRIS, ROJO, VERDE = "#22D3EE", "#5B6B7A", "#F87171", "#34D399"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
HAY_KEY = bool(os.getenv("LLM_API_KEY"))

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.estado { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #7D8B99;
          border: 1px solid #1F2A36; border-radius: 6px; padding: 6px 10px; display: inline-block; }
.estado b { color: #34D399; font-weight: 600; }
.reclamo { border: 1px solid #1F2A36; border-radius: 10px; background: #0F151C; padding: 14px 16px; }
</style>
""", unsafe_allow_html=True)


def tema(chart: alt.Chart) -> alt.Chart:
    return (chart.configure(background="transparent")
            .configure_axis(labelColor="#9AA7B4", titleColor="#9AA7B4", gridColor="#1F2A36", domainColor="#2A3644")
            .configure_legend(labelColor="#9AA7B4", titleColor="#9AA7B4")
            .configure_view(strokeWidth=0))


@st.cache_resource(show_spinner=False)
def agente(demo: bool):
    return crear_agente(demo)


@st.cache_data(show_spinner=False)
def leer(sql: str, resultados: bool = False) -> pd.DataFrame:
    ruta = ruta_resultados() if resultados else ruta_db()
    if not ruta.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(sql).df()
    except duckdb.CatalogException:
        return pd.DataFrame()
    finally:
        con.close()


def resumen() -> dict:
    df = leer("SELECT corrida, datos FROM resumen", resultados=True)
    return {r.corrida: json.loads(r.datos) for r in df.itertuples()} if len(df) else {}


# ----------------------------------------------------------------- barra lateral

if not ruta_db().exists():
    st.error("Falta la base. Corre `python -m reclamos generar`.", icon=":material/error:")
    st.stop()

with st.sidebar:
    st.subheader("Killa · reclamos")
    n = leer("SELECT COUNT(*) AS n, min(fecha_hora)::DATE AS d, max(fecha_hora)::DATE AS h FROM reclamos").iloc[0]
    st.caption(f"{n.n:,} reclamos · {MESES[n.d.month - 1]} – {MESES[n.h.month - 1]} {n.h.year} · datos sintéticos")
    modo = st.radio("Modelo", ["LLM (API)", "Demo sin API key"], index=0 if HAY_KEY else 1, disabled=not HAY_KEY,
                    help="Sin LLM_API_KEY el agente corre el flujo fijo: macro actual más verificación por MCP.")
    demo = modo.startswith("Demo")
    st.caption("El texto del reclamo llega al modelo con DNI, tarjeta, celular y correo enmascarados.")

st.markdown('<p class="encabezado"><span>&gt;</span> reclamos-mcp</p>', unsafe_allow_html=True)
st.caption("Agente de primera línea que verifica cada reclamo en los sistemas por MCP antes de abonar, "
           "rechazar o derivar.")
st.markdown(f'<div class="estado"><b>●</b> servidor killa-sistemas · 9 herramientas · perfil asistente_reclamos · '
            f'modelo: {"demo" if demo else os.getenv("LLM_MODELO", MODELO_DEFECTO)}</div>', unsafe_allow_html=True)
st.write("")

t_atender, t_indicadores, t_juez, t_permisos = st.tabs([
    ":material/support_agent: Atender", ":material/compare_arrows: AS IS vs TO BE",
    ":material/gavel: Juez", ":material/shield: Permisos"])

# ----------------------------------------------------------------- atender

with t_atender:
    reclamos = leer("""SELECT r.id_reclamo, r.codigo, r.fecha_hora, r.canal, r.texto, v.tipo, v.caso,
                              v.accion_correcta, v.tiene_inyeccion
                       FROM reclamos r JOIN aux_verdad v USING (id_reclamo) ORDER BY id_reclamo""")
    c1, c2 = st.columns([1, 2])
    with c1:
        solo_inyeccion = st.toggle("Solo reclamos con instrucciones para el asistente")
        lista = reclamos[reclamos.tiene_inyeccion] if solo_inyeccion else reclamos
        cod = st.selectbox("Reclamo", lista.codigo.tolist(), index=0)
    fila = reclamos[reclamos.codigo == cod].iloc[0]
    with c2:
        st.markdown(f'<div class="reclamo"><span class="mono">{fila.codigo} · {fila.fecha_hora:%d/%m/%Y %H:%M} · '
                    f'{fila.canal}</span><br><br>{fila.texto}</div>', unsafe_allow_html=True)
        st.caption("Así lo escribió el cliente. El agente recibe la versión enmascarada.")

    if st.button("Atender con el agente", type="primary", icon=":material/play_arrow:"):
        ag = agente(demo)
        ag.sistemas.ops = Operaciones()  # cada corrida parte de cero
        with st.spinner("Consultando los sistemas..."):
            try:
                st.session_state.res = ag.atender(int(fila.id_reclamo))
            except Exception as e:  # se muestra el error en vez de romper la app
                st.error(f"Algo falló: {e}")
                st.stop()
    res = st.session_state.get("res")
    if res is not None and res.id_reclamo == int(fila.id_reclamo):
        esperado = "ESCALAR_SUPERVISOR" if fila.tiene_inyeccion else fila.accion_correcta
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Acción registrada", res.accion.replace("_", " ").lower())
        m2.metric("Abono", f"S/ {res.monto_abonado:,.2f}")
        m3.metric("Llamadas MCP", len(res.pasos))
        m4.metric("Denegadas", res.denegadas)
        if res.accion == esperado:
            st.success(f"Coincide con el caso real ({fila.caso}).", icon=":material/check_circle:")
        else:
            st.warning(f"El caso real es {fila.caso}: correspondía {esperado.replace('_', ' ').lower()}.",
                       icon=":material/report:")
        st.markdown("**Mensaje al cliente**")
        st.write(res.mensaje)
        st.markdown("**Traza**")
        for i, p in enumerate(res.pasos, 1):
            icono = ":material/block:" if not p.permitido else (":material/error:" if p.error else ":material/check_circle:")
            with st.expander(f"{i:02d} · {p.herramienta}", icon=icono):
                if p.pensamiento:
                    st.caption(p.pensamiento)
                st.json(p.entrada)
                st.code(p.salida[:3000], language="json")

# ----------------------------------------------------------------- indicadores

with t_indicadores:
    datos = resumen()
    if "as_is" not in datos:
        st.info("Corre `python -m reclamos evaluar --demo` para calcular los indicadores.", icon=":material/info:")
    else:
        a = datos["as_is"]
        corridas = [k for k in datos if k.startswith(("demo", "llm"))]
        corrida = st.selectbox("Corrida TO BE", corridas, format_func=lambda k: datos[k]["modelo"])
        b = datos[corrida]
        c = st.columns(4)
        c[0].metric("Bien encaminados", f"{b['acierto']:.1%}", f"{(b['acierto'] - a['bien_derivados_primera']) * 100:+.1f} pp vs macro")
        c[1].metric("Cerrados en primer contacto", f"{b['cerrados_en_primer_contacto']:.1%}")
        c[2].metric("Abonos indebidos", f"{b['abonos_indebidos_n']}")
        c[3].metric("Bloqueos innecesarios", f"{b['bloqueos_innecesarios']}")
        st.caption(f"En el historial AS IS: {a['abonos_indebidos_n']} abonos indebidos por "
                   f"S/ {a['abonos_indebidos_soles']:,.0f} y {a['bloqueos_innecesarios']} tarjetas bloqueadas sin "
                   f"ser fraude. TO BE sobre {b['reclamos']:,} reclamos.")

        st.markdown("**Bien encaminados a la primera, por tipo de reclamo**")
        macro = leer("SELECT tipo, bien_derivados AS valor FROM macro_por_tipo", True).assign(metodo="Macro actual")
        agente_t = leer(f"SELECT tipo, avg(acierto::INT) AS valor FROM to_be_{corrida} GROUP BY tipo", True) \
            .assign(metodo=b["modelo"])
        comp = pd.concat([macro, agente_t])
        comp["tipo"] = comp.tipo.str.replace("_", " ")
        barras = alt.Chart(comp).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("tipo:N", title=None, sort="-x", axis=alt.Axis(labelLimit=220)),
            x=alt.X("valor:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            yOffset="metodo:N",
            color=alt.Color("metodo:N", title=None, scale=alt.Scale(range=[GRIS, ACENTO]),
                            legend=alt.Legend(orient="top")),
            tooltip=["tipo", "metodo", alt.Tooltip("valor:Q", format=".1%")])
        st.altair_chart(tema(barras.properties(height=340)), width="stretch")

        st.markdown("**AS IS: días hábiles hasta la respuesta (promedio por mes del reclamo)**")
        mens = leer("SELECT * FROM mensual_as_is ORDER BY mes", True)
        mens["periodo"] = [f"{MESES[d.month - 1]} {d.year}" for d in pd.to_datetime(mens.mes)]
        base = alt.Chart(mens).encode(
            x=alt.X("periodo:O", title=None, sort=list(mens.periodo), axis=alt.Axis(labelAngle=0)))
        linea = base.mark_line(color=ACENTO, strokeWidth=2.5).encode(
            y=alt.Y("promedio_dias:Q", title="días hábiles", scale=alt.Scale(zero=False, nice=True)),
            tooltip=["periodo", alt.Tooltip("promedio_dias:Q", format=".1f"), "mediana_dias",
                     alt.Tooltip("fuera_de_plazo:Q", format=".1%")])
        st.altair_chart(tema((linea + linea.mark_circle(color=ACENTO, size=60)).properties(height=260)),
                        width="stretch")
        st.caption(f"Historial simulado del proceso actual: {a['fuera_de_plazo']:.1%} de los reclamos se respondió "
                   f"después de 15 días hábiles y {a['rederivados']:.1%} pasó por más de un área.")

        st.markdown("**Detalle por caso**")
        st.dataframe(leer(f"SELECT * FROM por_tipo_{corrida} ORDER BY tipo, caso", True), hide_index=True,
                     width="stretch", column_config={"acierto": st.column_config.ProgressColumn(
                         format="percent", min_value=0, max_value=1)})

# ----------------------------------------------------------------- juez

with t_juez:
    j = resumen().get("juez")
    if not j:
        st.info("Corre `python -m reclamos juez` para calibrar el juez.", icon=":material/info:")
    else:
        st.caption("El juez revisa el mensaje al cliente frente a lo registrado. Se mide contra mensajes con "
                   "etiqueta de revisión, la mitad con un defecto insertado.")
        filas = []
        for nombre, m in j.items():
            filas.append({"juez": nombre, "mensajes": m["n"], "aprueba lo bueno": m["sensibilidad"],
                          "rechaza lo malo": m["especificidad"], "kappa": m["kappa"]})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch", column_config={
            "aprueba lo bueno": st.column_config.NumberColumn(format="percent"),
            "rechaza lo malo": st.column_config.NumberColumn(format="percent"),
            "kappa": st.column_config.NumberColumn(format="%.2f")})
        rec = pd.concat([pd.DataFrame(m["recall_por_defecto"]).assign(juez=k) for k, m in j.items()])
        rec["defecto"] = rec.defecto.str.replace("_", " ")
        barras = alt.Chart(rec).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("defecto:N", title=None, sort="-x", axis=alt.Axis(labelLimit=220)), yOffset="juez:N",
            x=alt.X("detectados:Q", title="defectos detectados", axis=alt.Axis(format="%"),
                    scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("juez:N", title=None, scale=alt.Scale(range=[GRIS, ACENTO]), legend=alt.Legend(orient="top")),
            tooltip=["juez", "defecto", "mensajes", alt.Tooltip("detectados:Q", format=".0%")])
        st.altair_chart(tema(barras.properties(height=300)), width="stretch")
        for nombre, m in j.items():
            for tabla, o in m.get("objetivos", {}).items():
                st.caption(f"{nombre} sobre {tabla}: aprueba {o['observada']:.1%}; corregido por su error medido, "
                           f"{o['corregida']:.1%} (IC 95% {o['ic_bajo']:.1%} a {o['ic_alto']:.1%}).")

# ----------------------------------------------------------------- permisos

with t_permisos:
    @st.cache_data(show_spinner=False)
    def catalogo() -> pd.DataFrame:
        from mcp import Client

        async def listar():
            async with Client(crear_servidor(Sistemas(ruta_db()))) as c:
                return (await c.list_tools()).tools
        filas = []
        for t in asyncio.run(listar()):
            an = t.annotations
            fila = {"herramienta": t.name, "solo lectura": bool(an and an.read_only_hint),
                    "destructiva": bool(an and an.destructive_hint)}
            for nombre, perfil in PERFILES.items():
                fila[nombre] = t.name in perfil.herramientas
            filas.append(fila)
        return pd.DataFrame(filas)

    st.caption("Lo que expone el servidor MCP y lo que ve cada perfil. El host filtra la lista antes de "
               "pasársela al modelo y el servidor revalida las reglas en cada escritura.")
    st.dataframe(catalogo(), hide_index=True, width="stretch")
    p = PERFILES["asistente_reclamos"]
    st.caption(f"asistente_reclamos: tope de abono S/ {p.tope_abono:.0f}, {p.max_abonos} abono por reclamo, "
               f"{p.max_llamadas} llamadas como máximo, solo sobre el cliente del reclamo y sobre movimientos "
               "que ya listó.")
