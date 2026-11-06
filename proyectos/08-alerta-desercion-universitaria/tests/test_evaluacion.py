import numpy as np
import pandas as pd
import pytest

from desercion import evaluacion as ev


def _pred():
    # 4 alumnos, semanas 2 a 4; el alumno 1 es el de mayor puntaje siempre
    filas = []
    for w in (2, 3, 4):
        for a, p in zip((1, 2, 3, 4), (0.9, 0.6, 0.3, 0.1)):
            filas.append({"id_alumno": a, "periodo": "2026-1", "semana": w, "p": p - 0.01 * w, "f": a != 2})
    return pd.DataFrame(filas)


def test_simular_contactos_respeta_capacidad_y_no_repite():
    c = ev.simular_contactos(_pred(), "p", capacidad=1, semanas=range(2, 5))
    assert c.sort_values("semana_lista").id_alumno.tolist() == [1, 2, 3]
    assert c.id_alumno.is_unique
    c = ev.simular_contactos(_pred(), "p", capacidad=1, semanas=range(2, 5), filtro="f")
    assert c.sort_values("semana_lista").id_alumno.tolist() == [1, 3, 4]


def test_resumen_contactos_a_tiempo():
    contactos = pd.DataFrame({"id_alumno": [1, 2, 3], "periodo": "2026-1", "semana_lista": [2, 3, 4]})
    fin = pd.DataFrame({"id_alumno": [1, 2, 3, 4], "periodo": "2026-1", "deserta": [1, 1, 0, 1],
                        "semana_abandono": [17, 4, np.nan, 6]})
    r = ev.resumen_contactos(contactos, fin)
    # 1: llamado en s3, se iba entre ciclos -> a tiempo; 2: llamado en s4, dejó de ir en s4 -> a tiempo
    assert r["desertores"] == 3 and r["alcanzados"] == 2
    assert r["precision"] == pytest.approx(2 / 3)
    assert r["anticipacion_mediana"] == pytest.approx((14 + 0) / 2)


def test_calibracion_perfecta():
    rng = np.random.default_rng(1)
    p = rng.random(200_000)
    y = rng.random(200_000) < p
    assert ev.ece(y, p) < 0.01
    assert ev.ece(y, np.clip(p + 0.2, 0, 1)) > 0.1
    assert len(ev.calibracion(y, p, bins=10)) == 10


def test_metricas_semana():
    df = pd.DataFrame({"semana": [2] * 4 + [3] * 4, "deserta": [1, 0, 0, 0] * 2,
                       "s": [0.9, 0.1, 0.2, 0.3] * 2, "q": [0.9, 0.1, 0.2, 0.3] * 2})
    m = ev.metricas_semana(df, {"m": ("s", "q")})
    assert (m.auc_pr == 1).all() and (m.auc_roc == 1).all()
