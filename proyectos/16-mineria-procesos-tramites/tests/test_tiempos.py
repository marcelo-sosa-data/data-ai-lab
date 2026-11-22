import numpy as np

from tramites import catalogos as K
from tramites import tiempos as T


def test_espera_mas_servicio_es_el_total(ev_t):
    con = ev_t[ev_t["servicio_h"].notna()]
    assert np.allclose(con["espera_h"] + con["servicio_h"], con["total_h"])
    assert (con["espera_h"] >= -1e-6).all() and (con["servicio_h"] >= 0).all()


def test_casos_y_plazo(log):
    c = T.casos(log)
    a = c[c["estado"] == "Atendido"]
    assert (a["fuera_plazo"] == (a["dias_habiles"] > a["tipo"].map(K.PLAZO_DIAS))).all()
    # toda excepción es un retiro
    assert set(c.loc[c["excepcion"], "tipo"]) <= {K.RETIRO}


def test_reparto_del_tiempo_suma_uno(ev_t, log):
    r = T.reparto_tiempo(ev_t, log.tramites)
    assert np.allclose(r.groupby("tipo")["pct"].sum(), 1)


def test_el_area_reporta_menos_de_lo_que_el_tramite_pasa_en_ella(ev_t, log):
    a = T.por_area(ev_t, log.tramites).dropna(subset=["atencion_media_h"])
    assert (a["en_area_media_h"] > a["atencion_media_h"]).all()
    d = a[(a["area"] == K.DIRECCION) & (a["tipo"] == K.CONVALIDACION)].iloc[0]
    assert d["en_area_media_h"] > 5 * d["atencion_media_h"]
