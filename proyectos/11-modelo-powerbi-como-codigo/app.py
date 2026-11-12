"""
Tablero del modelo de matrícula como código.

    streamlit run app.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "src"))

from semantico import despliegue as D  # noqa: E402
from semantico.cli import AMBIENTES, CASOS, DATOS, LEGADO, MODELO, PERIODO_ACTUAL, RESULTADOS  # noqa: E402
from semantico.errores import ERRORES, aplicar  # noqa: E402
from semantico.legado import cargar_legado, comparar, revisar_legado  # noqa: E402
from semantico.motor import Motor  # noqa: E402
from semantico.pruebas import cargar_casos, conexion_sql, correr  # noqa: E402
from semantico.reglas import revisar  # noqa: E402
from semantico.tmdl import cargar_modelo  # noqa: E402

st.set_page_config(page_title="Modelo de matrícula · Mirasol", page_icon=":material/schema:", layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.nota { color: #7D8B99; font-size: .85rem; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO = "#22D3EE"
GRIS = "#5B6B7A"
TEXTO = "#D6DEE6"
FONDO = "#0B0F14"


@alt.theme.register("mirasol", enable=True)
def tema_oscuro():
    return {"config": {
        "background": FONDO, "view": {"stroke": None},
        "axis": {"labelColor": TEXTO, "titleColor": "#7D8B99", "gridColor": "#1F2A36", "domainColor": "#1F2A36",
                 "labelFont": "JetBrains Mono", "titleFont": "Inter"},
        "legend": {"labelColor": TEXTO, "titleColor": "#7D8B99"},
        "title": {"color": TEXTO, "font": "Inter"},
    }}


# ----------------------------------------------------------------- carga

@st.cache_resource(show_spinner="Cargando el modelo y los datos...")
def cargar():
    modelo = cargar_modelo(MODELO)
    motor = Motor.desde_carpeta(modelo, DATOS)
    casos = cargar_casos(CASOS)
    con = conexion_sql(DATOS)
    return modelo, motor, casos, con


@st.cache_data(show_spinner="Corriendo las pruebas de medidas...")
def pruebas_df() -> pd.DataFrame:
    modelo, motor, casos, con = cargar()
    filas = []
    for r in correr(motor, casos, con):
        filas.append({"estado": "ok" if r.ok else "falla", "caso": r.caso.id, "medida": r.caso.medida,
                      "grupos": len(r.esperado), "ms": round(r.segundos * 1000),
                      "detalle": r.error or "; ".join(f"{k}: {e} vs {o}" for k, e, o in r.diferencias[:2])})
    return pd.DataFrame(filas)


def resultados_guardados() -> dict:
    return json.loads(RESULTADOS.read_text(encoding="utf-8")) if RESULTADOS.exists() else {}


def fmt(v, medida: str = "") -> str:
    if v is None:
        return "-"
    formato = cargar()[0].medidas.get(medida)
    if formato and "%" in formato.formato:
        return f"{v:+.1%}" if formato.formato.startswith("+") else f"{v:.1%}"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.2f}"
    return f"{v:,.0f}"


if not (DATOS / "matricula.parquet").exists():
    st.error("No hay datos. Corre primero: python -m semantico generar")
    st.stop()

modelo, motor, casos, con = cargar()
guardado = resultados_guardados()

st.markdown('<p class="encabezado">modelo<span>.</span>matricula</p>', unsafe_allow_html=True)
st.caption("Universidad Mirasol (ficticia) · modelo semántico en TMDL con pruebas, reglas y despliegue por ambientes")

tabs = st.tabs([":material/compare_arrows: Antes y ahora", ":material/fact_check: Pruebas",
                ":material/bug_report: Errores sembrados", ":material/query_stats: Medidas",
                ":material/rocket_launch: Cambios y ambientes"])

# ----------------------------------------------------------------- antes y ahora

with tabs[0]:
    periodos = sorted(motor.datos["Periodo"]["periodo"])
    periodo = st.segmented_control("Periodo", periodos, default=PERIODO_ACTUAL, key="per_legado")
    legado = cargar_legado(LEGADO)
    filas = comparar(motor, legado, {"Periodo[periodo]": periodo})
    df = pd.DataFrame([f.__dict__ for f in filas])

    mat = df[df["indicador"] == "Alumnos matriculados"].copy()
    oficial = mat.loc[mat["reporte"] == "Modelo único", "valor"].iloc[0]
    c = st.columns(4)
    for col, (_, f) in zip(c, mat.iterrows()):
        delta = None if f["reporte"] == "Modelo único" else f"{f['valor'] - oficial:+,.0f} vs modelo"
        col.metric(f["reporte"], f"{f['valor']:,.0f}", delta, delta_color="off")
    st.caption(f"Alumnos matriculados en {periodo} según cada reporte. Registros cuenta a quien se retiró de "
               "todos sus cursos, Finanzas solo a quien pagó la primera cuota y Dirección solo a alumnos regulares.")

    mat["color"] = mat["reporte"].map(lambda r: ACENTO if r == "Modelo único" else GRIS)
    graf = alt.Chart(mat).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("reporte:N", title=None, sort=list(mat["reporte"]), axis=alt.Axis(labelLimit=220)),
        x=alt.X("valor:Q", title="Alumnos matriculados", axis=alt.Axis(tickCount=6)),
        color=alt.Color("color:N", scale=None),
        tooltip=["reporte", "medida", alt.Tooltip("valor:Q", format=",.0f")],
    ).properties(height=190)
    st.altair_chart(graf, width="stretch")

    st.markdown("**Los otros indicadores**")
    resto = df[df["indicador"] != "Alumnos matriculados"].copy()
    resto["valor"] = [f"{v:.1%}" if v is not None and v < 1.5 else fmt(v) for v in resto["valor"]]
    st.dataframe(resto, hide_index=True, width="stretch")

    st.markdown("**Reglas sobre las medidas de cada reporte**")
    hall = revisar_legado(modelo, legado)
    filas_h = [{"reporte": r, "regla": h.regla, "severidad": h.severidad, "medida": h.objeto, "detalle": h.detalle}
               for r, hs in hall.items() for h in hs]
    st.dataframe(pd.DataFrame(filas_h), hide_index=True, width="stretch", height=280)

# ----------------------------------------------------------------- pruebas

with tabs[1]:
    pr = pruebas_df()
    hallazgos = revisar(modelo, {c.medida for c in casos})
    c = st.columns(4)
    c[0].metric("Medidas", len(modelo.medidas))
    c[1].metric("Casos que pasan", f"{(pr['estado'] == 'ok').sum()} de {len(pr)}")
    c[2].metric("Hallazgos de reglas", len(hallazgos))
    c[3].metric("Tiempo de las pruebas", f"{pr['ms'].sum() / 1000:.1f} s")
    st.dataframe(pr, hide_index=True, width="stretch",
                 column_config={"estado": st.column_config.TextColumn(width="small")})

    elegido = st.selectbox("Ver un caso", [c.id for c in casos])
    caso = next(c for c in casos if c.id == elegido)
    if caso.descripcion:
        st.caption(caso.descripcion)
    i, d = st.columns(2)
    with i:
        st.markdown(f"DAX de [{caso.medida}]")
        st.code(modelo.medidas[caso.medida].expresion, language="sql")
    with d:
        st.markdown("SQL de referencia")
        st.code(caso.sql.strip(), language="sql")
    from semantico.pruebas import correr_caso  # noqa: E402
    r = correr_caso(motor, con, caso)
    claves = sorted(set(r.esperado) | set(r.obtenido), key=str)
    st.dataframe(pd.DataFrame({"grupo": [str(k) if k is not None else "(total)" for k in claves],
                               "SQL": [fmt(r.esperado.get(k), caso.medida) for k in claves],
                               "DAX": [fmt(r.obtenido.get(k), caso.medida) for k in claves]}),
                 hide_index=True, width="stretch")

# ----------------------------------------------------------------- errores sembrados

with tabs[2]:
    errores = guardado.get("errores")
    if not errores:
        st.info("Todavía no hay resultados. Corre: python -m semantico errores (unos 25 s)")
    else:
        er = pd.DataFrame(errores)
        atrapados = int(er["atrapado"].sum())
        c = st.columns(4)
        c[0].metric("Errores sembrados", len(er))
        c[1].metric("Bloquean el merge", f"{atrapados} de {len(er)}")
        c[2].metric("Solo los ven las reglas", int(er["controles"].map(lambda x: x == ["reglas"]).sum()))
        c[3].metric("Solo los ven las pruebas", int(er["controles"].map(lambda x: x == ["pruebas"]).sum()))
        er["atrapado por"] = er.apply(lambda f: ", ".join(f["controles"]) if f["atrapado"]
                                      else "no bloquea (aviso " + ", ".join(f["avisos"]) + ")", axis=1)
        er["pruebas que fallan"] = er["pruebas_fallidas"].map(len)
        er["reglas"] = er["reglas"].map(", ".join)
        st.dataframe(er[["id", "descripcion", "atrapado por", "reglas", "pruebas que fallan"]],
                     hide_index=True, width="stretch", height=560)

# ----------------------------------------------------------------- medidas

with tabs[3]:
    i, d = st.columns([1, 2])
    with i:
        nombre = st.selectbox("Medida", sorted(modelo.medidas))
        por = st.selectbox("Por", ["Sede[sede]", "Carrera[carrera]", "Carrera[facultad]", "Matricula[modalidad]",
                                   "Matricula[tipo_alumno]", "Curso[ciclo]", "Alumno[tipo_colegio]"])
        periodo_m = st.selectbox("Periodo", sorted(motor.datos["Periodo"]["periodo"]), index=5)
        m = modelo.medidas[nombre]
        st.caption(m.descripcion)
        st.code(m.expresion, language="sql")
    with d:
        try:
            res = motor.evaluar(nombre, {"Periodo[periodo]": periodo_m}, por)
        except Exception as e:  # noqa: BLE001
            st.warning(str(e))
            res = {}
        if res:
            dm = pd.DataFrame({"grupo": [str(k) for k in res], "valor": list(res.values())})
            pct = "%" in m.formato
            st.altair_chart(alt.Chart(dm).mark_bar(color=ACENTO, cornerRadiusEnd=3).encode(
                y=alt.Y("grupo:N", title=None, sort="-x", axis=alt.Axis(labelLimit=240)),
                x=alt.X("valor:Q", title=nombre, axis=alt.Axis(format="%" if pct else ",")),
                tooltip=["grupo", alt.Tooltip("valor:Q", format=".1%" if pct else ",.2f")],
            ).properties(height=max(160, 34 * len(dm))), width="stretch")
        else:
            st.caption("La medida queda en blanco con estos filtros.")

        # serie por periodo: el eje no arranca en cero
        serie = motor.evaluar(nombre, por="Periodo[periodo]")
        if len(serie) > 1:
            ds = pd.DataFrame({"periodo": list(serie), "valor": list(serie.values())})
            base = alt.Chart(ds).encode(
                x=alt.X("periodo:O", title=None, sort=list(ds["periodo"]), axis=alt.Axis(labelAngle=0)),
                y=alt.Y("valor:Q", title=nombre, scale=alt.Scale(zero=False, nice=True),
                        axis=alt.Axis(format=".1%" if "%" in m.formato else ",")),
                tooltip=["periodo", alt.Tooltip("valor:Q", format=",.3f")])
            st.altair_chart((base.mark_line(color=ACENTO, strokeWidth=2.5) + base.mark_circle(color=ACENTO, size=60))
                            .properties(height=260, title=f"{nombre} por periodo"), width="stretch")

# ----------------------------------------------------------------- cambios y ambientes

with tabs[4]:
    st.markdown("**Así ve un pull request quien lo revisa**")
    st.caption("Elige un cambio y mira el plan que el CI deja en el resumen del PR: qué objetos cambian y cuánto se "
               "mueven los números del periodo actual.")
    opciones = {f"{e.id} · {e.descripcion}": e for e in ERRORES}
    elegido = st.selectbox("Cambio", list(opciones), index=6)
    with tempfile.TemporaryDirectory() as tmp:
        nuevo = cargar_modelo(aplicar(MODELO, opciones[elegido], Path(tmp)))
    p = D.plan(modelo, nuevo, DATOS, {"Periodo[periodo]": PERIODO_ACTUAL})
    st.markdown(D.plan_markdown(p).split("\n", 1)[1])

    st.markdown("**Ambientes**")
    amb = D.cargar_ambientes(AMBIENTES)
    st.dataframe(pd.DataFrame([{"ambiente": k, "workspace": v["workspace"],
                                "RutaDatos": v["parametros"]["RutaDatos"],
                                "id del workspace en": v["variable_workspace_id"]} for k, v in amb.items()]),
                 hide_index=True, width="stretch")
    st.markdown('<p class="nota">El TMDL del repositorio apunta a dev. construir copia el modelo y reemplaza '
                'los parámetros; prod se publica solo después de que test pasa y alguien aprueba el environment '
                'en GitHub.</p>', unsafe_allow_html=True)
