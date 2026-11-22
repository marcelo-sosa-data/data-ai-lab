import pandas as pd

from generar_datos import generar_casos, simular
from tramites import catalogos as K


def test_misma_semilla_mismos_casos():
    a, b = generar_casos(0.05, 3), generar_casos(0.05, 3)
    pd.testing.assert_frame_equal(a, b)


def test_reglas_rediseñadas():
    casos = generar_casos(0.08, 4)
    ev, fines = simular(casos, K.ESCENARIOS["e4"][1], 4)
    no_becados = set(casos.loc[(casos["tipo"] == K.RETIRO) & ~casos["becado"], "id_tramite"])
    assert not ev[ev["id_tramite"].isin(no_becados) & (ev["actividad"] == K.VISTO_BUENO)].shape[0]
    # el pago se verifica antes de que Dirección evalúe
    pago = ev[ev["actividad"] == K.VERIFICAR_PAGO].groupby("id_tramite")["fin"].min()
    evalua = ev[ev["actividad"] == K.EVALUAR].groupby("id_tramite")["fin"].min()
    comunes = pago.index.intersection(evalua.index)
    assert (pago[comunes] <= evalua[comunes]).all()
    # se firma martes y viernes
    assert set(ev.loc[ev["actividad"] == K.FIRMAR, "fin"].dt.weekday) == {1, 4}


def test_casos_de_prueba_quedan_cerrados_al_corte():
    casos = generar_casos(0.08, 4)
    ev, fines = simular(casos, K.Reglas(), 4)
    prueba = casos[casos["registro"].between(K.INICIO_PRUEBA, K.FIN_PRUEBA)]
    f = fines.set_index("id_tramite").reindex(prueba["id_tramite"])
    assert (f["fin"] <= K.CORTE).mean() > 0.97
