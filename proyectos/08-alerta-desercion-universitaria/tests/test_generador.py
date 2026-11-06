import duckdb
import numpy as np

from generar_datos import generar
from desercion.datos import desenlaces


def test_misma_semilla_mismos_datos(tmp_path):
    a = generar(tmp_path / "a.duckdb", escala=0.05, seed=11)
    b = generar(tmp_path / "b.duckdb", escala=0.05, seed=11)
    q = "SELECT COUNT(*), SUM(asistidas), SUM(sesiones) FROM asistencia"
    ca, cb = duckdb.connect(str(a)), duckdb.connect(str(b))
    assert ca.execute(q).fetchone() == cb.execute(q).fetchone()
    assert ca.execute("SELECT SUM(nota) FROM evaluaciones").fetchone() == \
        cb.execute("SELECT SUM(nota) FROM evaluaciones").fetchone()


def test_periodo_en_curso_hasta_semana_10(base):
    act = base.periodo_actual
    assert act == "2026-2" and base.semana_actual == 10
    assert base.asistencia[base.asistencia.periodo == act].semana.max() == 10
    assert set(base.evaluaciones[base.evaluaciones.periodo == act].evaluacion) == {"PC1", "Parcial"}


def test_sin_asistencia_despues_del_retiro(base):
    r = base.retiros.merge(base.asistencia, on=["id_alumno", "periodo"], suffixes=("_retiro", ""))
    assert (r.semana < r.semana_retiro).all()


def test_patrones(base):
    d = desenlaces(base)
    d = d[d.deserta.notna() & ~d.egresa]
    d = d.merge(base.matriculas[["id_alumno", "periodo", "beca_pct"]], on=["id_alumno", "periodo"])
    tasa = d.deserta.mean()
    assert 0.08 < tasa < 0.18
    assert d[d.ciclo <= 2].deserta.mean() > 2 * d[d.ciclo >= 5].deserta.mean()
    assert d[d.beca_pct > 0].deserta.mean() < d[d.beca_pct == 0].deserta.mean()
    # buena parte se va entre semestres y el pico dentro del ciclo cae después del parcial
    des = d[d.deserta == 1]
    assert 0.3 < (des.semana_abandono == 17).mean() < 0.7
    por_semana = des[des.semana_abandono <= 16].semana_abandono.value_counts()
    assert por_semana.idxmax() in (9, 10)


def test_causas_solo_de_desertores(base):
    d = desenlaces(base)
    c = base.causas.merge(d, on=["id_alumno", "periodo"])
    assert len(c) == len(base.causas)
    assert (c.deserta == 1).all()
    assert set(c.causa) <= {"académica o desenganche", "económica", "personal", "traslado"}
    assert np.isin(c.semana_abandono_real, np.arange(1, 18)).all()
