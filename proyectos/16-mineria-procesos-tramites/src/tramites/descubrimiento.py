"""
Descubrimiento del proceso real a partir del log, con PM4Py: variantes,
grafo de seguimiento directo (DFG) con frecuencias y tiempos, y su dibujo
en DOT para el tablero y en Mermaid para el README.
"""

from __future__ import annotations

import os

os.environ.setdefault("PM4PY_SHOW_PROGRESS_BAR", "False")

import pandas as pd  # noqa: E402
import pm4py  # noqa: E402

from . import catalogos as K  # noqa: E402

CORTO = {
    K.REGISTRAR: "Registrar", K.REVISAR_EXP: "Revisar exp.", K.OBSERVAR_EXP: "Observar exp.",
    K.SUBSANAR: "Subsanar", K.EVALUAR: "Evaluar sílabos", K.OBSERVAR_SIL: "Observar sílabos",
    K.EMITIR: "Emitir resol.", K.FIRMAR: "Firmar", K.VERIFICAR_PAGO: "Verificar pago",
    K.OBSERVAR_PAGO: "Observar pago", K.PAGAR: "Pagar", K.REGISTRAR_CONV: "Registrar conv.",
    K.NOTIFICAR: "Notificar", K.ARCHIVAR: "Archivar", K.REVISAR_SOL: "Revisar sol.",
    K.OBSERVAR_SOL: "Observar sol.", K.VISTO_BUENO: "Visto bueno", K.RECHAZAR_DIR: "Rechazo dir.",
    K.VERIFICAR_DEUDA: "Verificar deuda", K.OBSERVAR_DEUDA: "Observar deuda",
    K.PAGAR_DEUDA: "Pagar deuda", K.APROBAR_RETIRO: "Aprobar retiro",
    K.DEVOLVER_PLAZO: "Devolver por plazo", K.EMITIR_EXCEPCION: "Resol. excepción",
    K.RECHAZAR_EXT: "Rechazo extemp.",
}


def a_pm4py(eventos: pd.DataFrame) -> pd.DataFrame:
    """Formato de PM4Py. El orden lo da la hora de fin: muchas actividades no tienen hora de inicio."""
    df = eventos[["id_tramite", "actividad", "fin", "orden"]].sort_values(["id_tramite", "orden"])
    return pm4py.format_dataframe(df, case_id="id_tramite", activity_key="actividad",
                                  timestamp_key="fin")


def variantes(eventos: pd.DataFrame, casos: pd.DataFrame) -> pd.DataFrame:
    """Cada secuencia distinta de actividades, cuántos trámites la siguen y cuánto duran."""
    seq = eventos.groupby("id_tramite")["actividad"].agg(lambda s: " > ".join(CORTO.get(a, a) for a in s))
    d = casos.set_index("id_tramite")[["tipo", "duracion_dias", "estado"]].join(seq.rename("variante"))
    d = d.dropna(subset=["variante"])
    res = d.groupby(["tipo", "variante"]).agg(tramites=("estado", "size"),
                                              mediana_dias=("duracion_dias", "median")).reset_index()
    res["pct"] = res["tramites"] / res.groupby("tipo")["tramites"].transform("sum")
    res = res.sort_values(["tipo", "tramites"], ascending=[True, False])
    res["rango"] = res.groupby("tipo").cumcount() + 1
    return res.reset_index(drop=True)


def dfg(eventos: pd.DataFrame) -> pd.DataFrame:
    """Arcos del DFG con frecuencia y mediana de horas calendario entre una actividad y la siguiente."""
    df = a_pm4py(eventos)
    frec, inicio, fin = pm4py.discover_dfg(df)
    rend, _, _ = pm4py.discover_performance_dfg(df)
    filas = [{"desde": a, "hacia": b, "n": n, "mediana_h": rend[(a, b)]["median"] / 3600}
             for (a, b), n in frec.items()]
    filas += [{"desde": "Inicio", "hacia": a, "n": n, "mediana_h": 0.0} for a, n in inicio.items()]
    filas += [{"desde": a, "hacia": "Fin", "n": n, "mediana_h": 0.0} for a, n in fin.items()]
    return pd.DataFrame(filas).sort_values("n", ascending=False).reset_index(drop=True)


def _filtrar(arcos: pd.DataFrame, min_pct: float) -> pd.DataFrame:
    total = arcos.loc[arcos["desde"] == "Inicio", "n"].sum()
    return arcos[arcos["n"] >= min_pct * total]


def a_dot(arcos: pd.DataFrame, min_pct: float = 0.02, metrica: str = "n") -> str:
    """DOT en tema oscuro. Grosor por frecuencia; color cian en los arcos más lentos."""
    a = _filtrar(arcos, min_pct)
    nmax = a["n"].max()
    lento = a.loc[~a["desde"].isin(["Inicio"]) & ~a["hacia"].isin(["Fin"]), "mediana_h"].quantile(0.8)
    lineas = [
        'digraph G { rankdir=LR; bgcolor="#0B0F14"; pad=0.3; nodesep=0.35; ranksep=0.45;',
        'node [shape=box style="rounded,filled" fillcolor="#121820" color="#2A3644" '
        'fontcolor="#D6DEE6" fontname="Inter" fontsize=11];',
        'edge [color="#4B5A6A" fontcolor="#7D8B99" fontname="JetBrains Mono" fontsize=9];',
        '"Inicio" [shape=circle label="" width=0.25 fillcolor="#22D3EE" color="#22D3EE"];',
        '"Fin" [shape=doublecircle label="" width=0.2 fillcolor="#D6DEE6" color="#D6DEE6"];',
    ]
    for r in a.itertuples():
        etiqueta = f"{r.n:,}" if metrica == "n" else _horas(r.mediana_h)
        color = "#22D3EE" if (r.mediana_h >= lento and r.desde != "Inicio" and r.hacia != "Fin") else "#4B5A6A"
        ancho = 0.6 + 3.4 * r.n / nmax
        lineas.append(f'"{CORTO.get(r.desde, r.desde)}" -> "{CORTO.get(r.hacia, r.hacia)}" '
                      f'[label="{etiqueta}" penwidth={ancho:.2f} color="{color}"];')
    lineas.append("}")
    return "\n".join(lineas)


def _horas(h: float) -> str:
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} d"


def a_mermaid(arcos: pd.DataFrame, min_pct: float = 0.03) -> str:
    """Mermaid del proceso descubierto, con la frecuencia en cada arco (para el README)."""
    a = _filtrar(arcos, min_pct)
    nombres = {}

    def nodo(x):
        if x not in nombres:
            nombres[x] = f"n{len(nombres)}"
        return nombres[x]

    lineas = ["flowchart LR"]
    for r in a.itertuples():
        d, h = nodo(r.desde), nodo(r.hacia)
        lineas.append(f"    {d} -- {r.n:,} --> {h}")
    defs = []
    for x, k in nombres.items():
        if x == "Inicio":
            defs.append(f"    {k}((Inicio))")
        elif x == "Fin":
            defs.append(f"    {k}(((Fin)))")
        else:
            defs.append(f"    {k}[{CORTO.get(x, x)}]")
    return "\n".join(lineas[:1] + defs + lineas[1:])
