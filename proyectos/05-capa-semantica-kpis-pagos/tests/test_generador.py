def test_comision_solo_en_aprobadas(con):
    malas = con.execute("""SELECT COUNT(*) FROM transacciones
        WHERE (estado = 'aprobada' AND comision <= 0) OR (estado = 'rechazada' AND comision <> 0)""").fetchone()[0]
    assert malas == 0


def test_rechazadas_tienen_motivo(con):
    n = con.execute("""SELECT COUNT(*) FROM transacciones
        WHERE (estado = 'rechazada') <> (motivo_rechazo IS NOT NULL)""").fetchone()[0]
    assert n == 0


def test_no_hay_arequipa_el_20_de_mayo(con):
    n = con.execute("""SELECT COUNT(*) FROM transacciones t JOIN comercios c USING (id_comercio)
        WHERE t.fecha = '2026-05-20' AND c.region = 'Arequipa'""").fetchone()[0]
    assert n == 0


def test_caida_del_emisor_en_su_ventana(con):
    dentro, fuera = con.execute("""
        SELECT AVG(CASE WHEN estado = 'aprobada' THEN 1.0 ELSE 0 END)
                 FILTER (WHERE extract(hour FROM fecha_hora) BETWEEN 11 AND 15),
               AVG(CASE WHEN estado = 'aprobada' THEN 1.0 ELSE 0 END)
                 FILTER (WHERE extract(hour FROM fecha_hora) NOT BETWEEN 11 AND 15)
        FROM transacciones WHERE fecha = '2026-08-14' AND emisor = 'Banco del Pacífico'""").fetchone()
    assert dentro < 0.6 and fuera > 0.88


def test_version_512_solo_en_android_y_desde_su_lanzamiento(con):
    plataformas, desde = con.execute("""SELECT LIST(DISTINCT plataforma), MIN(fecha) FROM transacciones
                                        WHERE version_app = '5.12'""").fetchone()
    assert set(plataformas) <= {"android", "ios"} and str(desde) >= "2026-09-03"


def test_qr_crece_y_baja_el_take_rate(con):
    df = con.execute("""SELECT date_trunc('month', fecha) AS m, AVG((metodo = 'qr')::INT) AS qr,
                               SUM(comision) / SUM(monto) FILTER (WHERE estado = 'aprobada') AS take_rate
                        FROM transacciones GROUP BY 1 ORDER BY 1""").df()
    assert df.qr.iloc[-1] > df.qr.iloc[0] + 0.15
    assert df.take_rate.iloc[-1] < df.take_rate.iloc[0]
