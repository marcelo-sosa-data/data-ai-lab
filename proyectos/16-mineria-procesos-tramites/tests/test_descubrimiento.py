import pandas as pd

from tramites import catalogos as K
from tramites import descubrimiento as D
from tramites import tiempos as T


def test_dfg_cuenta_las_transiciones(log):
    ev = log.eventos
    arcos = D.dfg(ev)
    seguidos = ev.assign(sig=ev.groupby("id_tramite")["actividad"].shift(-1)).dropna(subset=["sig"])
    esperado = len(seguidos[(seguidos["actividad"] == K.EMITIR) & (seguidos["sig"] == K.FIRMAR)])
    fila = arcos[(arcos["desde"] == K.EMITIR) & (arcos["hacia"] == K.FIRMAR)]
    assert int(fila["n"].iloc[0]) == esperado
    assert arcos.loc[arcos["desde"] == "Inicio", "n"].sum() == ev["id_tramite"].nunique()


def test_variantes_suman_todos_los_tramites(log):
    v = D.variantes(log.eventos, T.casos(log))
    assert v.groupby("tipo")["pct"].sum().round(6).eq(1).all()
    assert v["tramites"].sum() == log.eventos["id_tramite"].nunique()


def test_dibujos(log):
    arcos = D.dfg(log.eventos)
    dot = D.a_dot(arcos)
    assert dot.startswith("digraph") and '"Evaluar sílabos"' in dot
    mer = D.a_mermaid(arcos)
    assert mer.startswith("flowchart LR") and "((Inicio))" in mer and "(((Fin)))" in mer
