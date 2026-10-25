"""Que los números de los marts tengan sentido de negocio."""

import pytest

from matricula.consultas import periodo_anterior


@pytest.mark.parametrize("periodo, saltos, esperado", [
    ("2026-2", 1, "2026-1"), ("2026-1", 1, "2025-2"), ("2026-2", 2, "2025-2"), ("2025-1", 3, "2023-2"),
])
def test_periodo_anterior(periodo, saltos, esperado):
    assert periodo_anterior(periodo, saltos) == esperado


def test_retencion_empieza_en_100_y_esta_entre_0_y_1(consultas):
    r = consultas.retencion()
    assert (r.loc[r["periodos_desde_ingreso"] == 0, "tasa_retencion"] == 1).all()
    assert r["tasa_retencion"].between(0, 1).all()


def test_avance_es_acumulado_y_cierra_en_el_total(consultas):
    periodos = consultas.periodos()
    av = consultas.avance(periodos)
    total = consultas.matricula_por_periodo().set_index("periodo")["matriculados"]
    for p, g in av.groupby("periodo"):
        assert g["matriculados_acumulados"].is_monotonic_increasing
        assert g["matriculados_acumulados"].iloc[-1] == total[p]
        assert g["pct_del_total"].iloc[-1] == pytest.approx(1.0)


def test_ocupacion_no_supera_vacantes(consultas):
    oc = consultas.df("select max(ocupacion) as m from marts.mart_ocupacion_secciones")["m"].iloc[0]
    assert oc <= 1


def test_siguiente_periodo_solo_nulo_en_el_ultimo(consultas):
    df = consultas.df("""
        select periodo, count(*) filter (where se_matricula_siguiente is null) as nulos, count(*) as n
        from marts.fct_matricula_alumno group by periodo order by periodo
    """)
    assert (df["nulos"].iloc[:-1] == 0).all()
    assert df["nulos"].iloc[-1] == df["n"].iloc[-1]


def test_deuda_baja_la_continuidad(consultas):
    df = consultas.continuidad("deuda").set_index("segmento")["tasa_continua"]
    assert df["0 cuotas"] > df["3 o más"]


def test_matematica_i_esta_entre_los_cursos_filtro(consultas):
    top = consultas.cursos_filtro(n=5, min_inscritos=20)
    assert "Matemática I" in set(top["curso"])


def test_kpis_del_ultimo_periodo(consultas):
    k = consultas.kpis(consultas.periodos()[-1])
    assert k.matriculados > 0 and k.ingresantes > 0
    assert 0 <= k.pct_con_deuda <= 1
    assert k.matriculados_anio_anterior is not None
