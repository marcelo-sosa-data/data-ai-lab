from datetime import date

import numpy as np
import pandas as pd
from pymc_marketing.clv import rfm_summary

from cohortes import rfm as R

CORTE = date(2026, 4, 30)


def test_rfm_coincide_con_pymc_marketing(con):
    r = R.rfm(con, CORTE).set_index("customer_id")
    dias = con.execute(R.SQL_DIAS, [CORTE]).df()
    ref = rfm_summary(dias, "id_cliente", "dia", monetary_value_col="ingreso",
                      observation_period_end=pd.Timestamp(CORTE), time_unit="D").set_index("customer_id")
    ref = ref.loc[r.index]
    for c in ("frequency", "recency", "T"):
        assert np.array_equal(r[c].to_numpy(), ref[c].to_numpy()), c
    assert np.allclose(r.monetary_value, ref.monetary_value, atol=1e-6)


def test_dias_sin_ingreso_no_cuentan(con):
    # un cliente que solo transfiere no aparece en el RFM
    solo_transfiere = con.execute("""
        SELECT id_cliente FROM transacciones WHERE fecha_hora < ?::DATE + 1
        GROUP BY 1 HAVING SUM(ingreso_neto) = 0 LIMIT 1
    """, [CORTE]).fetchone()
    r = R.rfm(con, CORTE)
    if solo_transfiere:
        assert solo_transfiere[0] not in set(r.customer_id)
    assert (r["T"] >= r.recency).all() and (r.frequency >= 0).all()


def test_compras_en_ventana(con):
    v = R.compras_en_ventana(con, date(2026, 5, 1), date(2026, 5, 31))
    total = con.execute("""
        SELECT COUNT(*) FROM (SELECT id_cliente, fecha_hora::DATE FROM transacciones
        WHERE fecha_hora >= '2026-05-01' AND fecha_hora < '2026-06-01' GROUP BY ALL HAVING SUM(ingreso_neto) > 0)
    """).fetchone()[0]
    assert v.compras_real.sum() == total
    assert v.ingreso_real.min() > 0
