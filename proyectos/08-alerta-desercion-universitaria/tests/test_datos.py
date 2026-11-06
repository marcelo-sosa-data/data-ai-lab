import numpy as np
import pandas as pd

from desercion.datos import Base, desenlaces, siguiente_periodo


def test_siguiente_periodo():
    assert siguiente_periodo("2025-1") == "2025-2"
    assert siguiente_periodo("2025-2") == "2026-1"


def _base_minima() -> Base:
    """Cuatro alumnos en 2025-1, con 2025-2 como periodo siguiente (en curso)."""
    mat = pd.DataFrame({"id_alumno": [1, 2, 3, 4, 1, 4], "periodo": ["2025-1"] * 4 + ["2025-2"] * 2,
                        "ciclo": [3, 5, 2, 10, 4, 1]})
    filas = []
    ultima = {1: 16, 2: 15, 3: 12, 4: 16}     # 3 deja de ir en la 12 pero hace retiro en la 9
    for a, u in ultima.items():
        for w in range(1, 17):
            if a == 3 and w >= 9:
                continue
            filas.append((a, "2025-1", w, 10, 8 if w <= u else 0))
    asis = pd.DataFrame(filas, columns=["id_alumno", "periodo", "semana", "sesiones", "asistidas"])
    lms = asis[["id_alumno", "periodo", "semana"]].assign(ingresos=1, minutos=10, tareas=0, tareas_entregadas=0)
    vacia = pd.DataFrame(columns=["id_alumno", "periodo"])
    return Base(alumnos=pd.DataFrame({"id_alumno": [1, 2, 3, 4]}),
                periodos=pd.DataFrame({"periodo": ["2025-1", "2025-2"], "semanas_con_datos": [16, 10]}),
                matriculas=mat, asistencia=asis, aula_virtual=lms, evaluaciones=vacia, cuotas=vacia,
                retiros=pd.DataFrame({"id_alumno": [3], "periodo": ["2025-1"], "semana": [9]}),
                egresados=pd.DataFrame({"id_alumno": [4], "periodo": ["2025-1"]}))


def test_desenlaces():
    d = desenlaces(_base_minima()).set_index(["id_alumno", "periodo"])
    # 1 vuelve; 2 termina y no vuelve (entre semestres); 3 se retira en la 9; 4 egresa
    assert d.loc[(1, "2025-1"), "deserta"] == 0
    assert d.loc[(2, "2025-1"), "deserta"] == 1 and d.loc[(2, "2025-1"), "semana_abandono"] == 17
    assert d.loc[(3, "2025-1"), "deserta"] == 1 and d.loc[(3, "2025-1"), "semana_abandono"] == 9
    assert d.loc[(4, "2025-1"), "deserta"] == 0 and d.loc[(4, "2025-1"), "egresa"]
    # el periodo en curso no tiene desenlace
    assert d.xs("2025-2", level="periodo").deserta.isna().all()
    assert np.isnan(d.loc[(1, "2025-1"), "semana_abandono"])
