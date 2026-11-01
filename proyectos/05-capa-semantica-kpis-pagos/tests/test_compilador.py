import pytest
import sqlglot

from kpis.compilador import DIALECTOS, SIN_DATO, Consulta
from kpis.modelo import ErrorSemantico


def test_ratio_es_suma_sobre_suma_y_no_promedio_de_ratios(capa, con):
    q = Consulta(metricas=["tasa_aprobacion"], grano="mes", desde="2026-08-01", hasta="2026-08-31")
    capa_val = capa.consultar(con, q).tasa_aprobacion.iloc[0]
    sum_sum, prom = con.execute("""
        WITH d AS (SELECT fecha, AVG(CASE WHEN estado = 'aprobada' THEN 1.0 ELSE 0 END) AS r,
                          COUNT(*) FILTER (WHERE estado = 'aprobada') AS a, COUNT(*) AS n
                   FROM transacciones WHERE fecha BETWEEN '2026-08-01' AND '2026-08-31' GROUP BY 1)
        SELECT SUM(a) / SUM(n), AVG(r) FROM d""").fetchone()
    assert capa_val == pytest.approx(sum_sum, abs=1e-12)
    assert abs(capa_val - prom) > 1e-6  # el promedio de ratios diarios da otra cosa


def test_tpv_por_rubro_cuadra_con_sql_a_mano(capa, con):
    df = capa.consultar(con, Consulta(metricas=["tpv"], dimensiones=["rubro"], filtros={"region": ["Lima"]}))
    esperado = dict(con.execute("""
        SELECT COALESCE(c.rubro, '(sin dato)'), SUM(t.monto) FROM transacciones t
        LEFT JOIN comercios c USING (id_comercio)
        WHERE t.estado = 'aprobada' AND COALESCE(c.region, '(sin dato)') = 'Lima' GROUP BY 1""").fetchall())
    assert dict(zip(df.rubro, df.tpv)) == pytest.approx({k: float(v) for k, v in esperado.items()})


def test_cobros_sin_comercio_quedan_como_sin_dato(capa, con):
    df = capa.consultar(con, Consulta(metricas=["transacciones"], dimensiones=["region"]))
    total = capa.consultar(con, Consulta(metricas=["transacciones"])).transacciones.iloc[0]
    assert SIN_DATO in set(df.region)
    assert df.transacciones.sum() == total


def test_derivada_es_division_de_metricas(capa, con):
    df = capa.consultar(con, Consulta(metricas=["tpv", "comercios_activos", "tpv_por_comercio"], grano="mes"))
    assert (df.tpv / df.comercios_activos).to_numpy() == pytest.approx(df.tpv_por_comercio.to_numpy())


def test_no_trae_join_si_no_hace_falta(capa):
    sql = capa.sql(Consulta(metricas=["tpv"], dimensiones=["emisor"]))
    assert "JOIN" not in sql
    sql = capa.sql(Consulta(metricas=["tpv"], filtros={"rubro": ["ropa"]}))
    assert "LEFT JOIN comercios" in sql


def test_incluir_medidas_devuelve_numerador_y_denominador(capa, con):
    df = capa.consultar(con, Consulta(metricas=["ticket_promedio"], grano="mes", incluir_medidas=True))
    assert {"tpv", "aprobadas"} <= set(df.columns)
    assert (df.tpv / df.aprobadas).to_numpy() == pytest.approx(df.ticket_promedio.to_numpy())


@pytest.mark.parametrize("dialecto", DIALECTOS)
def test_compila_y_reparsea_en_cada_dialecto(capa, dialecto):
    q = Consulta(metricas=["tasa_aprobacion", "tpv_por_comercio"], dimensiones=["hora", "cohorte"],
                 grano="semana", desde="2026-01-01", filtros={"region": ["Lima", "Cusco"]})
    sql = capa.sql(q, dialecto)
    sqlglot.parse_one(sql, read=dialecto)
    assert "NULLIF" in sql


def test_semana_iso_en_bigquery(capa):
    sql = capa.sql(Consulta(metricas=["tpv"], grano="semana"), "bigquery")
    assert "ISOWEEK" in sql


def test_errores_claros(capa):
    with pytest.raises(ErrorSemantico, match="no existe"):
        capa.sql(Consulta(metricas=["gmv"]))
    with pytest.raises(ErrorSemantico, match="dimensión distrito no existe"):
        capa.sql(Consulta(metricas=["tpv"], dimensiones=["distrito"]))
    with pytest.raises(ErrorSemantico, match="grano"):
        capa.sql(Consulta(metricas=["tpv"], grano="hora"))
    with pytest.raises(ErrorSemantico, match="dialecto"):
        capa.sql(Consulta(metricas=["tpv"]), "oracle")
