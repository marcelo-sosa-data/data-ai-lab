import pandas as pd

from experimentos.catalogo import por_id
from experimentos.decision import alerta_novedad, decidir, evaluar_guardrail
from experimentos.estadistica import Comparacion


def comp(rel, lo, hi, p=0.01):
    return Comparacion("cuped", 1000, 1000, 1.0, 1.0 + rel, rel, 0.01, p, rel, lo, hi)


NEUTRO = comp(0.0, -0.01, 0.01, 0.9)


def lecturas(**kw):
    base = {m: NEUTRO for m in ("pedidos", "gmv", "margen", "conversion", "ticket", "cancelacion")}
    return base | kw


def test_srm_invalida_antes_de_mirar_efectos():
    d = decidir(por_id("EXP-01"), 1e-8, lecturas(pedidos=comp(0.05, 0.03, 0.07)), 31_000, 29_500)
    assert d.veredicto == "invalidar"


def test_guardrail_con_daño_no_se_lanza():
    d = decidir(por_id("EXP-04"), 0.5, lecturas(pedidos=comp(0.02, 0.01, 0.04),
                                                cancelacion=comp(0.5, 0.4, 0.6)), 1000, 1000)
    assert d.veredicto == "no lanzar" and "cancelación" in d.motivo


def test_direccion_del_guardrail():
    # en cancelación, bajar es bueno: -20% no es daño
    assert evaluar_guardrail("cancelacion", 0.10, comp(-0.2, -0.3, -0.1)).estado == "ok"
    # en margen, bajar es malo
    assert evaluar_guardrail("margen", 0.03, comp(-0.08, -0.10, -0.06)).estado == "daño"
    # IC que no descarta -5% con margen de 3%, pero tampoco confirma el daño
    assert evaluar_guardrail("margen", 0.03, comp(-0.01, -0.05, 0.03)).estado == "sin concluir"


def test_lanzar_extender_y_sin_efecto():
    e = por_id("EXP-03")
    ok = decidir(e, 0.5, lecturas(gmv=comp(0.04, 0.02, 0.06)), 1000, 1000)
    assert ok.veredicto == "lanzar"
    ext = decidir(e, 0.5, lecturas(gmv=comp(0.04, 0.02, 0.06), pedidos=comp(-0.01, -0.04, 0.02)), 1000, 1000)
    assert ext.veredicto == "extender" and "-4.0%" in ext.motivo
    nada = decidir(e, 0.5, lecturas(gmv=comp(0.01, -0.01, 0.03, 0.3)), 1000, 1000)
    assert nada.veredicto == "no lanzar" and "Sin efecto" in nada.motivo


def test_alerta_de_novedad():
    sem = pd.DataFrame([{"semana": "1", "relativo": 0.08, "relativo_bajo": 0.06, "relativo_alto": 0.10,
                         "p_valor": 0.0001},
                        {"semana": "2+", "relativo": 0.014, "relativo_bajo": -0.01, "relativo_alto": 0.04,
                         "p_valor": 0.3}])
    assert "novedad" in alerta_novedad(sem)
    estable = sem.assign(relativo=[0.05, 0.045], relativo_alto=[0.07, 0.07])
    assert alerta_novedad(estable) == ""
