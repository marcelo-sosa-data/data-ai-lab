import numpy as np

from experimentos.asignacion import asignar
from experimentos.catalogo import EXPERIMENTOS


def test_una_exposicion_por_usuario_y_experimento(con):
    dup = con.execute("""SELECT COUNT(*) FROM (SELECT id_experimento, id_usuario FROM exposiciones
                         GROUP BY ALL HAVING COUNT(*) > 1)""").fetchone()[0]
    assert dup == 0


def test_la_variante_registrada_es_la_del_hash(con):
    for e in EXPERIMENTOS:
        df = con.execute("SELECT id_usuario, variante FROM exposiciones WHERE id_experimento = ?", [e.id]).df()
        esperado = np.where(asignar(df.id_usuario.to_numpy(), e.sal, e.reparto), "tratamiento", "control")
        assert (df.variante.to_numpy() == esperado).all()


def test_exposicion_dentro_de_la_ventana(con):
    fuera = con.execute("""SELECT COUNT(*) FROM exposiciones x JOIN experimentos e USING (id_experimento)
                           WHERE x.fecha_exposicion NOT BETWEEN e.fecha_inicio AND e.fecha_fin""").fetchone()[0]
    assert fuera == 0


def test_margen_cuadra(con):
    dif = con.execute("""SELECT MAX(ABS(margen - CASE WHEN cancelado THEN 0
                                ELSE comision + tarifa_envio - costo_rider END)) FROM pedidos""").fetchone()[0]
    assert dif < 0.02


def test_envio_gratis_solo_en_tratamiento_de_exp02(con):
    gratis = con.execute("""
        SELECT COALESCE(x.variante, 'fuera') AS v, COUNT(*) FROM pedidos p
        LEFT JOIN exposiciones x ON x.id_usuario = p.id_usuario AND x.id_experimento = 'EXP-02'
             AND p.fecha BETWEEN x.fecha_exposicion AND DATE '2026-05-17'
        WHERE p.tarifa_envio = 0 GROUP BY 1""").fetchall()
    assert dict(gratis).keys() == {"tratamiento"}
