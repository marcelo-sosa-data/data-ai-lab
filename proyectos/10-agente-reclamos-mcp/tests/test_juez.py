import pandas as pd
import pytest

from reclamos.juez import JuezReglas, corregir_con_intervalo, leer_veredicto, matriz, tasa_corregida
from reclamos.set_juez import armar


def test_matriz_y_kappa():
    e = pd.Series([True] * 50 + [False] * 50)
    j = pd.Series([True] * 45 + [False] * 5 + [True] * 10 + [False] * 40)
    m = matriz(e, j)
    assert (m["vp"], m["fn"], m["fp"], m["vn"]) == (45, 5, 10, 40)
    assert m["sensibilidad"] == pytest.approx(0.9) and m["especificidad"] == pytest.approx(0.8)
    assert m["kappa"] == pytest.approx(0.7)


def test_correccion_de_rogan_gladen():
    # si de verdad aprueba el 60%, un juez con sens 0.9 y esp 0.8 marcaría 0.6*0.9 + 0.4*0.2 = 0.62
    assert tasa_corregida(0.62, 0.9, 0.8) == pytest.approx(0.6)
    assert tasa_corregida(0.5, 0.5, 0.5) != tasa_corregida(0.5, 0.5, 0.5)  # nan: juez sin información


def test_intervalo_contiene_la_puntual():
    cal = pd.DataFrame({"etiqueta": [True] * 60 + [False] * 60,
                        "juez": [True] * 54 + [False] * 6 + [True] * 12 + [False] * 48})
    r = corregir_con_intervalo(cal, pd.Series([True] * 31 + [False] * 19))
    assert r["ic_bajo"] <= r["corregida"] <= r["ic_alto"]
    assert r["corregida"] < r["observada"]  # el juez aprueba de más


def test_veredicto_ilegible_cuenta_como_desaprobado():
    assert not leer_veredicto("no sé").aprueba
    v = leer_veredicto('Aquí va: {"falla": [], "aprueba": true}')
    assert v.aprueba


def test_juez_reglas():
    j = JuezReglas()
    bueno = ("Hola, sobre su reclamo R-26-00001: verificamos el cargo de Botica Alameda del 2026-01-03 por "
             "S/ 35.51 y corresponde la devolución. Hemos abonado S/ 35.51 a su tarjeta.")
    assert j.evaluar(bueno, "ABONAR", 35.51).aprueba
    assert j.evaluar(bueno, "NO_PROCEDE", 0).falla == ["coherente", "sin_promesas"]
    assert j.evaluar("Hola, lo derivamos a Contracargos y le avisaremos.", "ESCALAR_CONTRACARGOS", 0).falla == [
        "siguiente_paso"]


def test_set_del_juez(sistemas, ruta_db):
    import duckdb

    from reclamos import evaluacion as ev
    from reclamos.agente import AgenteReclamos
    from reclamos.llm import ModeloDemo

    con = duckdb.connect(str(ruta_db), read_only=True)
    verdad = ev.cargar_verdad(con)
    con.close()
    t = ev.tabla_resultados(AgenteReclamos(ModeloDemo(), sistemas).atender_lote(verdad.id_reclamo.tolist()), verdad)
    sj = armar(t, 60, seed=4)
    assert sj.etiqueta.sum() > 10 and (~sj.etiqueta).sum() > 10
    assert (sj.etiqueta == (sj.defecto == "ninguno")).all()
    assert armar(t, 60, seed=4).mensaje.tolist() == sj.mensaje.tolist()
