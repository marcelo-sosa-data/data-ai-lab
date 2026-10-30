from experimentos.aa import estudio_aa
from experimentos.analisis import leer
from experimentos.catalogo import por_id
from experimentos.planificacion import tabla_planificacion


def test_srm_de_exp05_esta_en_android_antiguo(con):
    lec = leer(con, por_id("EXP-05"))
    v = lec.srm_por_version.set_index("version_app")
    assert v.loc["android<6", "p_srm"] < 1e-4
    assert v.loc["android<6", "pct_tratamiento"] < 0.45
    assert (v.drop("android<6").p_srm > 0.001).all()


def test_exp04_rompe_el_guardrail_de_cancelacion(con):
    lec = leer(con, por_id("EXP-04"))
    estado = {g.metrica: g.estado for g in lec.decision.guardrails}
    assert estado["cancelacion"] == "daño"
    assert lec.decision.veredicto == "no lanzar"


def test_exp02_sube_ticket_y_baja_margen(con):
    lec = leer(con, por_id("EXP-02"))
    # con la base chica el ticket no alcanza significancia; el margen sí
    assert lec.lecturas["ticket"].relativo > 0
    assert lec.lecturas["margen"].relativo_alto < 0


def test_tablas_de_la_lectura(con):
    lec = leer(con, por_id("EXP-03"))
    assert set(lec.metricas.metodo) == {"welch", "cuped", "delta"}
    cup = lec.metricas[(lec.metricas.metodo == "cuped") & (lec.metricas.metrica != "conversion")]
    assert (cup.reduccion_varianza > 0.1).all()
    assert list(lec.semanas.semana)[-1] == "2+"
    assert lec.secuencial.dia.max() == 28
    assert (lec.segmentos.q_valor >= lec.segmentos.p_valor - 1e-12).all()


def test_aa_y_planificacion(con):
    curva, res = estudio_aa(con, repeticiones=300)
    assert res["dias"] == 28 and len(curva) == 28
    # una sola mirada queda cerca del 5%; mirar todos los días, muy por encima
    assert curva.una_mirada.iloc[-1] < 0.10
    assert curva.mirando_cada_dia.iloc[-1] > curva.una_mirada.iloc[-1] * 2
    assert curva.msprt_cada_dia.iloc[-1] < 0.06
    plan = tabla_planificacion(con)
    assert (plan.mde_con_cuped < plan.mde_sin_cuped).all()
    assert plan.groupby("metrica").mde_con_cuped.apply(lambda s: s.is_monotonic_decreasing).all()
