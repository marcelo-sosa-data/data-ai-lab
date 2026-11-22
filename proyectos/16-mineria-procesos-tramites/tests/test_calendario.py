from datetime import datetime

import numpy as np
import pandas as pd

from tramites.calendario import a_calendario, a_habiles, dias_habiles, etiqueta_dia, etiqueta_mes


def test_ida_y_vuelta_en_horario():
    t = pd.Timestamp("2026-03-11 10:30")
    assert a_calendario(a_habiles(t)) == t


def test_noche_y_fin_de_semana_no_suman_horas():
    viernes = a_habiles(datetime(2026, 3, 13, 17, 0))
    assert a_habiles(datetime(2026, 3, 13, 22, 0)) == viernes
    assert a_habiles(datetime(2026, 3, 15, 12, 0)) == viernes
    assert a_habiles(datetime(2026, 3, 16, 8, 0)) == viernes


def test_feriado_no_es_habil():
    # 29 de junio de 2026 (lunes) es feriado
    assert a_habiles(datetime(2026, 6, 29, 12)) == a_habiles(datetime(2026, 6, 26, 17))


def test_dias_habiles_de_una_semana():
    assert dias_habiles(datetime(2026, 3, 9, 8), datetime(2026, 3, 16, 8)) == 5


def test_vectorizado():
    fechas = pd.Series(pd.to_datetime(["2026-01-05 09:00", "2026-01-05 18:00"]))
    h = a_habiles(fechas)
    assert isinstance(h, np.ndarray) and h[1] - h[0] == 8


def test_etiquetas_en_espanol():
    assert etiqueta_mes("2026-09-01") == "set 2026"
    assert etiqueta_dia("2026-12-24") == "24 dic"
