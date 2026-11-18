"""
Tablero de cuentas por pagar: bandeja de revisión, calidad de lectura y
proceso actual contra el rediseñado.

    streamlit run app.py
"""

from __future__ import annotations

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

from comprobantes.cli import cargar_env, umbral_guardado  # noqa: E402
from comprobantes.esquema import CAMPOS  # noqa: E402
from comprobantes.procesar import cargar_contexto  # noqa: E402
from comprobantes.reglas import validar  # noqa: E402
from comprobantes.rutas import ruta_db, ruta_imagenes, ruta_resultados  # noqa: E402
from comprobantes.ruteo import decidir  # noqa: E402

cargar_env()
st.set_page_config(page_title="Comprobantes · Comercial Tayta", page_icon=":material/receipt_long:",
                   layout="wide")

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem; color: #22D3EE; }
[data-testid="stMetricLabel"] p { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #7D8B99; }
[data-testid="stMetricDelta"] { font-family: 'JetBrains Mono', monospace; }
.encabezado { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 600; margin: 0; }
.encabezado span { color: #22D3EE; }
.estado { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #7D8B99;
          border: 1px solid #1F2A36; border-radius: 6px; padding: 6px 10px; display: inline-block; }
.estado b { color: #34D399; font-weight: 600; }
.motivo { font-family: 'JetBrains Mono', monospace; font-size: .78rem; color: #FBBF24;
          border: 1px solid #3A3220; border-radius: 4px; padding: 2px 6px; margin-right: 4px; }
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)

ACENTO, GRIS, AMBAR = "#22D3EE", "#475569", "#FBBF24"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]
NOMBRE_CAMPO = {"tipo": "tipo", "ruc_emisor": "RUC emisor", "ruc_receptor": "RUC receptor", "serie": "serie",
                "numero": "número", "fecha_emision": "fecha de emisión", "moneda": "moneda",
                "base_imponible": "base imponible", "igv": "IGV", "total": "total", "orden_compra": "orden de compra"}
NOMBRE_ANOMALIA = {"excede_oc": "total sobre la OC", "no_habido": "proveedor no habido", "duplicado": "reenvío duplicado",
                   "receptor_errado": "factura a otro RUC", "igv_mal": "IGV mal calculado", "total_mal": "total no cuadra"}


def tema(grafico: alt.Chart) -> alt.Chart:
    return (grafico.configure(background="transparent")
            .configure_axis(labelColor="#9AA7B4", titleColor="#7D8B99", gridColor="#1F2A36", domainColor="#1F2A36",
                            labelFont="JetBrains Mono", titleFont="Inter")
            .configure_legend(labelColor="#9AA7B4", titleColor="#7D8B99", labelFont="Inter", labelLimit=320)
            .configure_view(stroke=None))


def etiqueta_fecha(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day:02d} {MESES[d.month - 1]}"


@st.cache_data(show_spinner=False)
def cargar() -> dict | None:
    if not ruta_db().exists() or not ruta_resultados().exists():
        return None
    con = duckdb.connect(str(ruta_resultados()), read_only=True)
    try:
        datos = {t: con.execute(f"SELECT * FROM {t} WHERE corrida = 'demo'").df()
                 for t in ["lecturas", "decisiones", "aciertos", "curva_umbral", "resumen"]}
    except duckdb.CatalogException:
        return None
    finally:
        con.close()
    con = duckdb.connect(str(ruta_db()), read_only=True)
    datos["verdad"] = con.execute("SELECT * FROM aux_verdad").df()
    datos["padron"] = con.execute("SELECT ruc, razon_social FROM padron").df()
    con.close()
    datos["res"] = json.loads(datos["resumen"]["datos"].iloc[0])
    return datos


D = cargar()

# ----------------------------------------------------------------- encabezado

st.markdown('<p class="encabezado"><span>&gt;</span> cuentas por pagar</p>', unsafe_allow_html=True)
st.caption("Comercial Tayta · comprobantes de compra sin XML · set y oct 2026 · datos sintéticos")
if D is None:
    st.warning("No hay resultados. Corre `python -m comprobantes todo` y vuelve a cargar.", icon=":material/warning:")
    st.stop()

res, proc = D["res"], D["res"]["proceso_prueba"]
r = res["ruteo_prueba"]
st.markdown(
    f'<div class="estado"><b>●</b> extractor: {res["extractor"]} · {res["segundos_por_comprobante"]:.2f} s por '
    f'comprobante · umbral calibrado con setiembre, cifras de octubre · '
    f'LLM: {os.getenv("LLM_MODELO", "sin configurar") if os.getenv("LLM_API_KEY") else "sin API key"}</div>',
    unsafe_allow_html=True)
st.write("")
a, b = proc["as_is"], proc["to_be"]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Se registran solos", f"{r['pct_aprobados']:.1%}", f"{r['aprobados']} de {r['comprobantes']}",
          delta_color="off", delta_arrow="off")
c2.metric("Aprobados con algún campo mal", f"{r['tasa_error_aprobados']:.2%}", f"{r['aprobados_con_error']} comprobante",
          delta_color="off", delta_arrow="off")
c3.metric("Errores vistos antes de pagar", f"{b['detectadas_antes_de_pagar']} de {proc['con_anomalia']}",
          f"hoy {a['detectadas_antes_de_pagar']}", delta_color="off", delta_arrow="off")
c4.metric("Días hasta detectar", f"{b['dias_a_deteccion']:.1f}", f"hoy {a['dias_a_deteccion']:.1f}", delta_color="off", delta_arrow="off")
c5.metric("Pagado con error sin ver", f"S/ {b['monto_pagado_sin_detectar']:,.0f}",
          f"hoy S/ {a['monto_pagado_sin_detectar']:,.0f}", delta_color="off", delta_arrow="off")

tab_bandeja, tab_lectura, tab_proceso, tab_probar = st.tabs([
    ":material/inbox: Bandeja de revisión", ":material/document_scanner: Calidad de lectura",
    ":material/account_tree: AS IS vs TO BE", ":material/play_circle: Leer un comprobante"])

v = D["verdad"].copy()
v["mes"] = pd.to_datetime(v["fecha_recepcion"]).dt.month
dec = D["decisiones"].merge(v, on="doc_id").merge(D["lecturas"][["doc_id", "comprobante", "confianza"]], on="doc_id")
razon = dict(zip(D["padron"]["ruc"], D["padron"]["razon_social"]))


def mostrar_comprobante(fila: pd.Series, lectura: dict, confianza: dict, obs: list[dict], destino: str) -> None:
    col_img, col_dat = st.columns([5, 4])
    with col_img:
        ruta = ruta_imagenes() / fila["archivo"]
        if ruta.exists():
            st.image(str(ruta), width="stretch")
        else:
            st.caption("La imagen no está en esta máquina; corre `python -m comprobantes generar`.")
    with col_dat:
        st.markdown(f"**{razon.get(fila['ruc_emisor'], fila['ruc_emisor'])}**")
        st.caption(f"recibido el {pd.Timestamp(fila['fecha_recepcion']):%d/%m/%Y} por {fila['captura']} · "
                   f"plantilla {fila['plantilla']}")
        filas = []
        for k in CAMPOS:
            verdad = fila[k]
            verdad = "" if pd.isna(verdad) else (pd.Timestamp(verdad).date().isoformat() if k == "fecha_emision" else verdad)
            leido = lectura.get(k)
            filas.append({"campo": NOMBRE_CAMPO[k], "leído": "" if leido is None else str(leido),
                          "confianza": confianza.get(k), "impreso": str(verdad)})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch",
                     column_config={"confianza": st.column_config.ProgressColumn(format="%.2f", min_value=0,
                                                                                 max_value=1)})
        st.caption("La columna «impreso» es la verdad de la simulación; en operación no existe.")
        if obs:
            for o in obs:
                if o["origen"] != "aviso":
                    st.markdown(f'<span class="motivo">{o["codigo"]}</span> {o["detalle"]}', unsafe_allow_html=True)
                else:
                    st.caption(f'{o["codigo"]}: {o["detalle"]}')
        (st.success if destino == "aprobado" else st.warning)(
            "Se registra solo" if destino == "aprobado" else "Va a la bandeja de revisión",
            icon=":material/check_circle:" if destino == "aprobado" else ":material/pending_actions:")


# ----------------------------------------------------------------- bandeja

with tab_bandeja:
    oct_ = dec[dec["mes"] == 10]
    bandeja = oct_[oct_["destino"] == "revision"].copy()
    bandeja["motivos_txt"] = bandeja["motivos"].map(lambda m: ", ".join(json.loads(m)))
    bandeja["proveedor"] = bandeja["ruc_emisor"].map(razon)
    st.caption(f"{len(bandeja)} comprobantes de octubre pasaron a revisión; {len(oct_) - len(bandeja)} se registraron "
               "solos. Cada fila trae el motivo, así quien revisa sabe qué mirar.")
    filtro = st.multiselect("Motivo", sorted({m for ms in bandeja["motivos"] for m in json.loads(ms)}),
                            placeholder="Todos")
    if filtro:
        bandeja = bandeja[bandeja["motivos"].map(lambda m: bool(set(json.loads(m)) & set(filtro)))]
    tabla = bandeja[["doc_id", "fecha_recepcion", "proveedor", "serie", "numero", "total", "moneda", "motivos_txt"]]
    sel = st.dataframe(
        tabla.rename(columns={"doc_id": "id", "fecha_recepcion": "recibido", "motivos_txt": "motivos"}),
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", height=300,
        column_config={"recibido": st.column_config.DateColumn(format="DD/MM/YYYY"),
                       "total": st.column_config.NumberColumn(format="%.2f")})
    if sel.selection.rows:
        fila = bandeja.iloc[sel.selection.rows[0]]
        st.divider()
        mostrar_comprobante(fila, json.loads(fila["comprobante"]), json.loads(fila["confianza"]),
                            json.loads(fila["observaciones"]), fila["destino"])
    else:
        st.caption("Selecciona una fila para ver la imagen, lo que se leyó y por qué está aquí.")

# ----------------------------------------------------------------- lectura

with tab_lectura:
    ac = D["aciertos"]
    ac_oct = ac[ac["mes"] == 10]
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Exactitud por campo, octubre")
        ex = ac_oct[CAMPOS].mean().rename("exactitud").reset_index().rename(columns={"index": "campo"})
        ex["campo"] = ex["campo"].map(NOMBRE_CAMPO)
        # puntos y no barras: el eje empieza en 94% para que se vea la diferencia entre campos
        ex["inicio"] = 0.94
        base = alt.Chart(ex).encode(
            y=alt.Y("campo:N", sort=list(ex.sort_values("exactitud")["campo"]), title=None,
                    axis=alt.Axis(labelLimit=220, labelOverlap=False)),
            tooltip=["campo", alt.Tooltip("exactitud:Q", format=".1%")])
        eje = alt.X("exactitud:Q", title=None, scale=alt.Scale(domain=[0.94, 1.0]), axis=alt.Axis(format="%"))
        g = base.mark_rule(color=GRIS, strokeWidth=2).encode(x=alt.X("inicio:Q", scale=alt.Scale(domain=[0.94, 1.0]),
                                                                       title=None), x2="exactitud:Q") + \
            base.mark_circle(color=ACENTO, size=110, opacity=1).encode(x=eje)
        st.altair_chart(tema(g.properties(height=330)), width="stretch")
        st.caption(f"{ac_oct['doc_correcto'].mean():.1%} de los comprobantes se leyó sin ningún error.")
    with col2:
        st.subheader("Por cómo llegó")
        por = ac_oct.groupby(["captura"])[CAMPOS + ["doc_correcto"]].mean()
        por = pd.DataFrame({"campos bien leídos": por[CAMPOS].mean(axis=1), "comprobante sin error": por["doc_correcto"],
                            "n": ac_oct.groupby("captura").size()})
        st.dataframe(por, width="stretch", column_config={
            "campos bien leídos": st.column_config.NumberColumn(format="percent"),
            "comprobante sin error": st.column_config.NumberColumn(format="percent")})
        por_p = ac_oct.groupby(["plantilla"])[["doc_correcto"]].mean().rename(columns={"doc_correcto": "comprobante sin error"})
        por_p["n"] = ac_oct.groupby("plantilla").size()
        st.dataframe(por_p, width="stretch",
                     column_config={"comprobante sin error": st.column_config.NumberColumn(format="percent")})

    st.subheader("Calibración del umbral de confianza, setiembre")
    curva = D["curva_umbral"].copy()
    if len(curva):
        curva["pct"] = curva["percentil"].map(lambda x: f"p{x * 100:g}")
        largo = curva.melt(id_vars=["percentil", "pct"], value_vars=["pct_aprobados", "tasa_error_aprobados"],
                           var_name="serie", value_name="valor")
        largo["serie"] = largo["serie"].map({"pct_aprobados": "se registran solos",
                                             "tasa_error_aprobados": "aprobados con algún campo mal"})
        base = alt.Chart(largo).encode(
            x=alt.X("pct:O", sort=list(curva["pct"]), title="umbral por campo (percentil de las lecturas correctas)",
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("valor:Q", title=None, axis=alt.Axis(format="%")),
            color=alt.Color("serie:N", scale=alt.Scale(range=[AMBAR, ACENTO]), title=None,
                            legend=alt.Legend(orient="top")),
            tooltip=["pct", "serie", alt.Tooltip("valor:Q", format=".2%")])
        st.altair_chart(tema((base.mark_line(strokeWidth=2.5) + base.mark_circle(size=55)).properties(height=280)),
                        width="stretch")
        elegido = curva.loc[curva["percentil"] == res["percentil"]].iloc[0]
        cero = curva[curva["aprobados_con_error"] == 0]
        texto = (f"Con el percentil elegido (p{res['percentil'] * 100:g}) se registra solo el "
                 f"{elegido['pct_aprobados']:.1%} de setiembre con {elegido['tasa_error_aprobados']:.2%} de error.")
        if len(cero):
            p0 = cero.iloc[0]
            texto += (f" Para llegar a cero errores hay que subir a p{p0['percentil'] * 100:g}, y ahí solo se "
                      f"registra solo el {p0['pct_aprobados']:.1%}.")
        st.caption(texto)

# ----------------------------------------------------------------- proceso

with tab_proceso:
    st.subheader("Mismos comprobantes de octubre, dos procesos")
    tabla = pd.DataFrame([
        ["Comprobantes que se digitan o corrigen a mano", f"{a['pct_digitado']:.0%}", f"{b['pct_digitado']:.1%}"],
        ["Errores del proveedor vistos antes de pagar", f"{a['detectadas_antes_de_pagar']} de {proc['con_anomalia']}",
         f"{b['detectadas_antes_de_pagar']} de {proc['con_anomalia']}"],
        ["Días promedio de la recepción a la detección", f"{a['dias_a_deteccion']:.1f}", f"{b['dias_a_deteccion']:.1f}"],
        ["Errores que nadie ve", str(a["nunca_detectadas"]), str(b["nunca_detectadas"])],
        ["Comprobantes con error pagados sin detectar", f"{a['pagadas_sin_detectar']} (S/ {a['monto_pagado_sin_detectar']:,.0f})",
         f"{b['pagadas_sin_detectar']} (S/ {b['monto_pagado_sin_detectar']:,.0f})"],
    ], columns=["Indicador", "AS IS", "TO BE"])
    st.dataframe(tabla, hide_index=True, width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Errores del proveedor en octubre")
        det = pd.DataFrame(res["deteccion_prueba"])
        det["error"] = det["anomalia"].map(NOMBRE_ANOMALIA)
        det["tras_corregir"] = det["con_motivo"] - det["motivo_al_leer"]
        det["sin_motivo"] = det["n"] - det["con_motivo"]
        largo = det.melt(id_vars=["error"], value_vars=["motivo_al_leer", "tras_corregir", "sin_motivo"],
                         var_name="tipo", value_name="comprobantes")
        largo["tipo"] = largo["tipo"].map({"motivo_al_leer": "con su motivo al leer",
                                           "tras_corregir": "al corregir la lectura",
                                           "sin_motivo": "no detectado"})
        largo["orden"] = largo["tipo"].map({"con su motivo al leer": 0, "al corregir la lectura": 1, "no detectado": 2})
        g = alt.Chart(largo).mark_bar(cornerRadiusEnd=2).encode(
            y=alt.Y("error:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False)),
            x=alt.X("comprobantes:Q", title="comprobantes"),
            color=alt.Color("tipo:N", scale=alt.Scale(domain=["con su motivo al leer", "al corregir la lectura",
                                                              "no detectado"], range=[ACENTO, AMBAR, GRIS]),
                            title=None, legend=alt.Legend(orient="top")),
            order=alt.Order("orden:Q"),
            tooltip=["error", "tipo", "comprobantes"])
        st.altair_chart(tema(g.properties(height=260)), width="stretch")
    with col2:
        st.subheader("Se registran solos, por semana")
        sem = dec.copy()
        sem["semana"] = pd.to_datetime(sem["fecha_recepcion"]).dt.to_period("W-SAT").dt.start_time
        sem = sem.groupby("semana").agg(aprobados=("destino", lambda s: (s == "aprobado").mean()),
                                        n=("doc_id", "size")).reset_index()
        sem["etiqueta"] = sem["semana"].map(etiqueta_fecha)
        base = alt.Chart(sem).encode(
            x=alt.X("etiqueta:O", sort=list(sem["etiqueta"]), title="semana que empieza", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("aprobados:Q", title=None, scale=alt.Scale(zero=False, nice=True), axis=alt.Axis(format="%")),
            tooltip=["etiqueta", alt.Tooltip("aprobados:Q", format=".1%"), "n"])
        st.altair_chart(tema((base.mark_line(color=ACENTO, strokeWidth=2.5) + base.mark_circle(color=ACENTO, size=55))
                             .properties(height=260)), width="stretch")
        st.caption(f"Entre {sem['aprobados'].min():.0%} y {sem['aprobados'].max():.0%} según la semana. La "
                   "semana del 30 de agosto solo tiene días de setiembre (la primera recepción es el 1).")

# ----------------------------------------------------------------- probar

with tab_probar:
    st.caption("Lee en vivo una imagen con Tesseract, la valida contra el padrón, las órdenes de compra y lo ya "
               "registrado, y decide el destino con el umbral calibrado.")
    doc_id = st.number_input("Comprobante (id)", min_value=int(v["doc_id"].min()), max_value=int(v["doc_id"].max()),
                             value=int(v.loc[v["mes"] == 10, "doc_id"].min()), step=1)
    if st.button("Leer", icon=":material/document_scanner:"):
        from comprobantes.ocr import ExtractorOCR

        fila = v.set_index("doc_id").loc[doc_id].copy()
        fila["doc_id"] = doc_id
        with st.spinner("Leyendo..."):
            lec = ExtractorOCR().extraer(ruta_imagenes() / fila["archivo"])
        con = duckdb.connect(str(ruta_db()), read_only=True)
        ctx = cargar_contexto(con)
        con.close()
        ctx.fecha_recepcion = pd.Timestamp(fila["fecha_recepcion"]).date()
        obs = validar(lec.comprobante, ctx)
        d = decidir(lec.comprobante, lec.confianza, obs, umbral_guardado())
        mostrar_comprobante(fila, json.loads(lec.comprobante.model_dump_json()), lec.confianza,
                            [o.__dict__ for o in obs], d.destino)
        st.caption("En esta lectura suelta no se revisan duplicados ni correlativos: esos controles dependen del "
                   "orden de llegada y se aplican en el lote.")
