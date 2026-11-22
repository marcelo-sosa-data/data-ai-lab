import pandas as pd

from tramites import catalogos as K
from tramites import conformidad as C


def _traza(id_, actividades, tipo=K.CONVALIDACION):
    t0 = pd.Timestamp("2026-03-02 09:00")
    ev = pd.DataFrame({"id_tramite": id_, "actividad": actividades,
                       "fin": [t0 + pd.Timedelta(hours=i) for i in range(len(actividades))]})
    ev["inicio"] = pd.NaT
    ev["orden"] = range(len(ev))
    return ev, {"id_tramite": id_, "tipo": tipo, "estado": "Atendido"}


NORMAL = [K.REGISTRAR, K.REVISAR_EXP, K.EVALUAR, K.EMITIR, K.FIRMAR, K.VERIFICAR_PAGO,
          K.REGISTRAR_CONV, K.NOTIFICAR]


def _log(*trazas):
    ev = pd.concat([t[0] for t in trazas], ignore_index=True)
    return ev, pd.DataFrame([t[1] for t in trazas])


def test_traza_del_reglamento_es_conforme():
    con_obs = NORMAL[:2] + [K.OBSERVAR_EXP, K.SUBSANAR, K.REVISAR_EXP] + NORMAL[2:]
    ev, tr = _log(_traza("A", NORMAL), _traza("B", con_obs))
    al = C.alinear(ev, tr)
    assert (al["fitness"] == 1).all()


def test_registrar_sin_pago_es_desvio_y_falta_el_pago():
    sin_pago = [a for a in NORMAL if a != K.VERIFICAR_PAGO]
    ev, tr = _log(_traza("A", NORMAL), _traza("B", sin_pago))
    al = C.alinear(ev, tr).set_index("id_tramite")
    assert al.loc["A", "fitness"] == 1 and al.loc["B", "fitness"] < 1
    assert K.VERIFICAR_PAGO in al.loc["B", "falta"]
    c = C.controles(ev, tr).set_index("id_tramite")
    assert c.loc["B", "sin_pago"] == 1 and c.loc["A", "sin_pago"] == 0


def test_pago_observado_no_cuenta_como_verificado():
    obs = [K.REGISTRAR, K.REVISAR_EXP, K.EVALUAR, K.EMITIR, K.FIRMAR, K.VERIFICAR_PAGO,
           K.OBSERVAR_PAGO, K.REGISTRAR_CONV, K.NOTIFICAR]
    ev, tr = _log(_traza("A", obs))
    assert C.controles(ev, tr).iloc[0]["sin_pago"] == 1


def test_retiro_sin_visto_bueno():
    ret = [K.REGISTRAR, K.REVISAR_SOL, K.VERIFICAR_DEUDA, K.APROBAR_RETIRO, K.NOTIFICAR]
    ev, tr = _log(_traza("R", ret, K.RETIRO))
    assert C.controles(ev, tr).iloc[0]["sin_visto_bueno"] == 1
    assert C.alinear(ev, tr).iloc[0]["fitness"] < 1


def test_en_el_log_los_desvios_coinciden_con_los_controles(log):
    al = C.alinear(log.eventos, log.tramites)
    c = C.controles(log.eventos, log.tramites)
    m = al.merge(c, on=["id_tramite", "tipo"])
    marcado = m[["sin_pago", "sin_revision", "sin_visto_bueno"]].fillna(0).sum(axis=1) > 0
    assert (m.loc[marcado, "fitness"] < 1).all()
    assert 0.85 < (al["fitness"] == 1).mean() < 1
