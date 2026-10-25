"""El build completo sobre un export chico: modelos, tests de dbt y reglas de calidad."""

import json

import duckdb


def test_build_sin_fallas(build):
    res, _ = build
    assert res.error is None
    assert res.fallas == []
    assert res.contar("modelo", "success") == 22
    assert res.contar("test unitario", "pass") == 4


def test_unico_aviso_es_el_tope_de_creditos(build):
    res, _ = build
    assert [n.nombre for n in res.avisos] == ["warn_matricula_sobre_tope_creditos"]


def test_cada_anomalia_inyectada_se_detecta_exacta(build, raw, consultas):
    inyectadas = json.loads((raw / "_anomalias.json").read_text(encoding="utf-8"))["anomalias"]
    detectadas = dict(consultas.calidad()[["regla_id", "registros"]].itertuples(index=False))
    assert detectadas == inyectadas


def test_no_quedan_dobles_clics(consultas):
    n = consultas.df("""
        select count(*) as n from (
            select codigo_alumno, seccion_id, tipo_evento,
                   date_diff('second', lag(fecha_hora) over (
                       partition by codigo_alumno, seccion_id, tipo_evento order by fecha_hora), fecha_hora) as gap
            from intermedio.int_eventos_limpios
        ) where gap <= 60
    """)["n"].iloc[0]
    assert n == 0


def test_codigos_quedan_normalizados(consultas):
    n = consultas.df("""
        select count(*) as n from marts.fct_inscripciones
        where codigo_alumno <> upper(trim(codigo_alumno)) or codigo_alumno like '% %'
    """)["n"].iloc[0]
    assert n == 0


def test_corrida_queda_registrada(build):
    _, db = build
    con = duckdb.connect(str(db), read_only=True)
    corridas = con.execute("select exito, modelos, tests_warn from auditoria.corridas").fetchall()
    con.close()
    assert corridas[-1] == (True, 22, 1)
