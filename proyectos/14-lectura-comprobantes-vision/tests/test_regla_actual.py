from datetime import date

import pandas as pd

from comprobantes.regla_actual import deteccion_as_is, fecha_cierre


def test_fecha_cierre():
    assert fecha_cierre(date(2026, 9, 30)) == date(2026, 10, 12)
    assert fecha_cierre(date(2026, 12, 3)) == date(2027, 1, 12)


def test_deteccion_as_is():
    v = pd.DataFrame([
        # IGV mal, contado: se paga el 6 de octubre y se ve el 12 de noviembre
        dict(doc_id=1, anomalia="igv_mal", fecha_recepcion=date(2026, 10, 5), fecha_vencimiento=date(2026, 10, 6),
             total=100.0, moneda="PEN"),
        # IGV mal a 45 días: vence después del cierre, se ve antes de pagar
        dict(doc_id=2, anomalia="igv_mal", fecha_recepcion=date(2026, 9, 5), fecha_vencimiento=date(2026, 10, 20),
             total=100.0, moneda="PEN"),
        # excede la OC: hoy no lo ve nadie
        dict(doc_id=3, anomalia="excede_oc", fecha_recepcion=date(2026, 9, 5), fecha_vencimiento=date(2026, 12, 1),
             total=10.0, moneda="USD"),
        # duplicado exacto: lo bloquea el ERP el mismo día
        dict(doc_id=4, anomalia="duplicado", fecha_recepcion=date(2026, 9, 5), fecha_vencimiento=date(2026, 9, 6),
             total=50.0, moneda="PEN"),
        dict(doc_id=5, anomalia=None, fecha_recepcion=date(2026, 9, 5), fecha_vencimiento=date(2026, 9, 6),
             total=50.0, moneda="PEN"),
    ])
    d = deteccion_as_is(v).set_index("doc_id")
    assert len(d) == 4
    assert d.loc[1, "pagado_antes"] and d.loc[1, "dias_a_deteccion"] == 38
    assert not d.loc[2, "pagado_antes"]
    assert not d.loc[3, "detectado"] and d.loc[3, "pagado_antes"] and d.loc[3, "monto_soles"] == 37.5
    assert not d.loc[4, "pagado_antes"] and d.loc[4, "dias_a_deteccion"] == 0
