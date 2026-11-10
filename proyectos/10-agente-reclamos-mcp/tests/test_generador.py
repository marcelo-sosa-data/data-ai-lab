from conftest import caso


def test_cada_reclamo_tiene_su_caso_real(con):
    n_rec = con.execute("SELECT COUNT(*) FROM reclamos").fetchone()[0]
    n_ver = con.execute("SELECT COUNT(DISTINCT id_reclamo) FROM aux_verdad").fetchone()[0]
    assert n_rec == n_ver == 160
    assert con.execute("SELECT COUNT(*) - COUNT(DISTINCT id_movimiento) FROM movimientos").fetchone()[0] == 0


def test_el_duplicado_real_tiene_su_gemelo(con):
    v = caso(con, "caso = 'duplicado_real'")
    gemelos = con.execute("""
        SELECT COUNT(*) FROM movimientos a JOIN movimientos b
          ON a.id_tarjeta = b.id_tarjeta AND a.comercio = b.comercio AND a.monto = b.monto
         AND a.id_movimiento <> b.id_movimiento
         AND abs(epoch(a.fecha_hora) - epoch(b.fecha_hora)) <= 600
        WHERE a.id_movimiento = ? AND b.estado = 'liquidado'""", [int(v["id_movimiento_ref"])]).fetchone()[0]
    assert gemelos == 1


def test_recargas_y_pagos_reflejan_el_caso(con):
    v = caso(con, "caso = 'recarga_fallida'")
    estado = con.execute("SELECT estado_operador FROM recargas WHERE id_movimiento = ?",
                         [int(v["id_movimiento_ref"])]).fetchone()[0]
    assert estado == "fallida"
    v = caso(con, "caso = 'pago_colgado'")
    assert con.execute("SELECT aplicado FROM pagos WHERE id_pago = ?", [int(v["id_pago_ref"])]).fetchone()[0] is False


def test_la_membresia_solo_se_cobra_fuera_de_la_exoneracion(con):
    # salvo los cargos sembrados como error del sistema
    n = con.execute("""
        SELECT COUNT(*) FROM movimientos m JOIN tarjetas t USING (id_tarjeta)
        WHERE m.tipo = 'membresia' AND m.fecha_hora::DATE <= t.exonerada_hasta""").fetchone()[0]
    sembrados = con.execute("SELECT COUNT(*) FROM aux_verdad WHERE caso = 'membresia_exonerada'").fetchone()[0]
    assert n == sembrados


def test_hay_textos_con_datos_personales_e_inyeccion(con):
    textos = [t for (t,) in con.execute("SELECT texto FROM reclamos").fetchall()]
    assert any("DNI" in t for t in textos)
    assert con.execute("SELECT COUNT(*) FROM aux_verdad WHERE tiene_inyeccion").fetchone()[0] >= 1


def test_es_reproducible(tmp_path):
    import duckdb
    from generar_datos import generar

    a = duckdb.connect(str(generar(tmp_path / "a.duckdb", escala=0.03, seed=1)), read_only=True)
    b = duckdb.connect(str(generar(tmp_path / "b.duckdb", escala=0.03, seed=1)), read_only=True)
    q = "SELECT string_agg(texto, '|' ORDER BY id_reclamo) FROM reclamos"
    assert a.execute(q).fetchone() == b.execute(q).fetchone()
