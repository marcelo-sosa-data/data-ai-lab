import pandas as pd


def _verdad(carpeta, c):
    return pd.read_parquet(carpeta / "verdad" / f"{c}.parquet")


def test_postulantes_e_ingresantes_coinciden_con_la_verdad(con, carpeta):
    kpi = con.sql("SELECT * FROM kpi_campania").df().set_index("campania")
    for c in kpi.index:
        v = _verdad(carpeta, c)
        assert kpi.loc[c, "postulantes"] == v["postulo"].sum()
        assert kpi.loc[c, "ingresantes"] == v["ingreso"].sum()


def test_matriculados_no_pasan_la_verdad_y_quedan_cerca(con, carpeta):
    kpi = con.sql("SELECT * FROM kpi_campania").df().set_index("campania")
    for c in kpi.index:
        v = _verdad(carpeta, c)
        real = (v["ingreso"] & v["matriculado"]).sum()
        assert real * 0.9 <= kpi.loc[c, "matriculados"] <= real


def test_una_fila_por_inscripcion_y_sin_pruebas(con):
    dup = con.sql("SELECT count(*) FROM (SELECT campania, codigo_postulante FROM inscripciones "
                  "GROUP BY ALL HAVING count(*) > 1)").fetchall()[0][0]
    assert dup == 0
    assert con.sql("SELECT count(*) FROM inscripciones WHERE es_prueba").fetchall()[0][0] == 0


def test_se_queda_con_la_ultima_version(con):
    # en el export hay inscripciones repetidas como Inscrito y luego con resultado
    r = con.sql("""
        SELECT count(*) FROM inscripciones i
        JOIN stg_inscripciones s USING (campania, codigo_postulante)
        WHERE s.estado = 'Inscrito' AND i.estado IN ('Ingresó', 'No ingresó')
    """).fetchall()[0][0]
    assert r > 0


def test_pagos_se_asignan_por_referencia_y_por_documento(con):
    vias = dict(con.sql("SELECT via, count(*) FROM pagos_matricula GROUP BY via").fetchall())
    assert vias["referencia"] > vias["documento"] > vias.get("sin asignar", 0)


def test_avance_acumulado_cuadra_con_el_total(con):
    r = con.sql("""
        SELECT a.campania, max(a.postulantes_acum) AS acum, k.postulantes
        FROM avance_semanal a JOIN kpi_campania k USING (campania)
        GROUP BY a.campania, k.postulantes
    """).df()
    assert (r["acum"] == r["postulantes"]).all()


def test_comparativo_suma_igual_por_cada_dimension(con):
    df = con.sql("SELECT dimension, sum(actual) a, sum(anterior) b FROM comparativo GROUP BY 1").df()
    assert df["a"].nunique() == 1 and df["b"].nunique() == 1


def test_leads_convertidos_son_postulantes(con):
    r = con.sql("""
        SELECT count(*) FROM interesados i
        LEFT JOIN postulantes p USING (campania, clave_persona)
        WHERE i.clave_persona IS NOT NULL AND p.clave_persona IS NULL
    """).fetchall()[0][0]
    assert r == 0


def test_pendientes_son_ingresantes_sin_matricula(con):
    kpi = con.sql("SELECT pendientes_matricula FROM kpi_campania WHERE campania = '2027-1'").fetchall()[0][0]
    assert con.sql("SELECT count(*) FROM pendientes_matricula").fetchall()[0][0] == kpi
