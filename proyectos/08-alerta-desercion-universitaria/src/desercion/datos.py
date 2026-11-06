"""Carga de la base académica y definición de la deserción."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SEMANAS = 16
SEMANA_ENTRE_SEMESTRES = 17   # quien termina el ciclo y no se vuelve a matricular
TABLAS = ("alumnos", "periodos", "matriculas", "asistencia", "aula_virtual", "evaluaciones", "cuotas",
          "retiros", "egresados")


def siguiente_periodo(p: str) -> str:
    anio, sem = p.split("-")
    return f"{anio}-2" if sem == "1" else f"{int(anio) + 1}-1"


@dataclass
class Base:
    alumnos: pd.DataFrame
    periodos: pd.DataFrame
    matriculas: pd.DataFrame
    asistencia: pd.DataFrame
    aula_virtual: pd.DataFrame
    evaluaciones: pd.DataFrame
    cuotas: pd.DataFrame
    retiros: pd.DataFrame
    egresados: pd.DataFrame
    causas: pd.DataFrame | None = None

    @property
    def periodo_actual(self) -> str:
        return self.periodos.periodo.max()

    @property
    def semana_actual(self) -> int:
        return int(self.periodos.set_index("periodo").semanas_con_datos[self.periodo_actual])

    @property
    def periodos_cerrados(self) -> list[str]:
        """Periodos con el desenlace conocido (existe la matrícula del siguiente)."""
        ps = sorted(self.periodos.periodo)
        return ps[:-1]


def cargar(ruta: Path, con_causas: bool = False) -> Base:
    if not Path(ruta).exists():
        raise FileNotFoundError(f"No existe {ruta}. Corre primero: python -m desercion generar")
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        t = {n: con.execute(f"SELECT * FROM {n}").df() for n in TABLAS}
        if con_causas:
            t["causas"] = con.execute("SELECT * FROM aux_causas").df()
    finally:
        con.close()
    return Base(**t)


def desenlaces(base: Base) -> pd.DataFrame:
    """
    Una fila por matrícula (alumno, periodo) con el desenlace:

    - deserta: no egresó y no aparece matriculado el periodo siguiente (NaN en el periodo en curso)
    - semana_abandono: primera semana sin actividad. Si siguió yendo hasta la semana 15 o 16,
      el abandono es entre semestres (17). Si hizo retiro de ciclo antes, cuenta el retiro.
    """
    m = base.matriculas[["id_alumno", "periodo", "ciclo"]].copy()
    sig = base.matriculas[["id_alumno", "periodo"]].rename(columns={"periodo": "periodo_siguiente"})
    m["periodo_siguiente"] = m.periodo.map(siguiente_periodo)
    m = m.merge(sig.assign(vuelve=True), on=["id_alumno", "periodo_siguiente"], how="left")
    m = m.merge(base.egresados.assign(egresa=True), on=["id_alumno", "periodo"], how="left")
    m["vuelve"] = m.vuelve.notna()
    m["egresa"] = m.egresa.notna()
    cerrado = m.periodo.isin(base.periodos_cerrados)
    m["deserta"] = np.where(cerrado, (~m.vuelve & ~m.egresa).astype(float), np.nan)

    a = base.asistencia.merge(base.aula_virtual[["id_alumno", "periodo", "semana", "tareas_entregadas"]],
                              on=["id_alumno", "periodo", "semana"], how="left")
    activo = a[(a.asistidas > 0) | (a.tareas_entregadas > 0)]
    ultima = activo.groupby(["id_alumno", "periodo"]).semana.max().rename("ultima_semana_activa")
    m = m.merge(ultima, on=["id_alumno", "periodo"], how="left")
    m["ultima_semana_activa"] = m.ultima_semana_activa.fillna(0).astype(int)
    m = m.merge(base.retiros[["id_alumno", "periodo", "semana"]].rename(columns={"semana": "semana_retiro"}),
                on=["id_alumno", "periodo"], how="left")
    sem = np.where(m.ultima_semana_activa >= SEMANAS - 1, SEMANA_ENTRE_SEMESTRES, m.ultima_semana_activa + 1)
    sem = np.where(m.semana_retiro.notna(), np.minimum(sem, m.semana_retiro.fillna(99)), sem)
    m["semana_abandono"] = np.where(m.deserta == 1, sem, np.nan)
    return m.drop(columns=["periodo_siguiente", "vuelve"])
