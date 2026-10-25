"""Lecturas sobre los marts. La app y la CLI solo consumen marts, nunca staging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from .rutas import ruta_db


def periodo_anterior(periodo: str, saltos: int = 1) -> str:
    """'2026-2' -> '2026-1' (1 salto) o '2025-2' (2 saltos, mismo semestre del año anterior)."""
    anio, sem = int(periodo[:4]), int(periodo[-1])
    idx = anio * 2 + sem - 1 - saltos
    return f"{idx // 2}-{idx % 2 + 1}"


@dataclass
class Kpis:
    periodo: str
    matriculados: int
    matriculados_anio_anterior: int | None
    ingresantes: int
    ingresantes_anio_anterior: int | None
    pct_extemporanea: float
    pct_con_deuda: float
    secciones: int
    secciones_baja_demanda: int

    @staticmethod
    def variacion(actual: int, anterior: int | None) -> float | None:
        return None if not anterior else actual / anterior - 1


class Consultas:
    def __init__(self, ruta: Path | None = None):
        self.ruta = Path(ruta or ruta_db())
        if not self.ruta.exists():
            raise FileNotFoundError(f"No existe {self.ruta}. Corre: python -m matricula build")
        self.con = duckdb.connect(str(self.ruta), read_only=True)

    def cerrar(self) -> None:
        self.con.close()

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    # ------------------------------------------------------------- general

    def periodos(self) -> list[str]:
        return [r[0] for r in self.con.execute(
            "select distinct periodo from marts.fct_matricula_alumno order by 1").fetchall()]

    def matricula_por_periodo(self) -> pd.DataFrame:
        return self.df("""
            select periodo,
                   count(*) as matriculados,
                   count(*) filter (where es_ingresante) as ingresantes,
                   count(*) filter (where not es_ingresante) as continuadores,
                   round(avg(creditos_inscritos), 1) as creditos_promedio
            from marts.fct_matricula_alumno
            group by periodo order by periodo
        """)

    def kpis(self, periodo: str) -> Kpis:
        por = self.matricula_por_periodo().set_index("periodo")
        previo = periodo_anterior(periodo, 2)
        fila = self.con.execute("""
            select avg(matricula_extemporanea::int), avg((cuotas_impagas > 0)::int)
            from marts.fct_matricula_alumno where periodo = ?
        """, [periodo]).fetchone()
        sec = self.con.execute("""
            select count(*), count(*) filter (where categoria = 'Baja demanda')
            from marts.mart_ocupacion_secciones where periodo = ? and modalidad = 'Presencial'
        """, [periodo]).fetchone()
        return Kpis(
            periodo=periodo,
            matriculados=int(por.loc[periodo, "matriculados"]),
            matriculados_anio_anterior=int(por.loc[previo, "matriculados"]) if previo in por.index else None,
            ingresantes=int(por.loc[periodo, "ingresantes"]),
            ingresantes_anio_anterior=int(por.loc[previo, "ingresantes"]) if previo in por.index else None,
            pct_extemporanea=float(fila[0]),
            pct_con_deuda=float(fila[1]),
            secciones=int(sec[0]),
            secciones_baja_demanda=int(sec[1]),
        )

    # ------------------------------------------------------------- avance

    def avance(self, periodos: list[str]) -> pd.DataFrame:
        marcas = ", ".join("?" for _ in periodos)
        return self.df(f"""
            select periodo, dia, fecha, es_extemporanea, matriculados_dia,
                   matriculados_acumulados, ingresantes_acumulados, pct_del_total
            from marts.mart_avance_matricula
            where periodo in ({marcas})
            order by periodo, dia
        """, periodos)

    def dia_matricula_por_deuda(self) -> pd.DataFrame:
        """Día promedio de matrícula según si el alumno arrastraba deuda del ciclo anterior."""
        return self.df("""
            with previo as (
                select codigo_alumno, periodo, cuotas_impagas,
                       lag(cuotas_impagas) over (partition by codigo_alumno order by periodo) as impagas_previo,
                       lag(periodo) over (partition by codigo_alumno order by periodo) as periodo_previo
                from marts.fct_matricula_alumno
            )
            select
                case when p.impagas_previo > 0 then 'Con deuda del ciclo anterior' else 'Sin deuda' end as grupo,
                count(*) as alumnos,
                round(avg(f.dia_matricula), 1) as dia_promedio,
                round(avg(f.matricula_extemporanea::int), 4) as pct_extemporanea
            from marts.fct_matricula_alumno as f
            inner join previo as p using (codigo_alumno, periodo)
            where not f.es_ingresante and p.periodo_previo is not null
            group by 1 order by 1 desc
        """)

    # ------------------------------------------------------------- secciones

    def ocupacion_sede_turno(self, periodo: str) -> pd.DataFrame:
        return self.df("""
            select sede, turno, count(*) as secciones,
                   round(sum(inscritos_cierre) / sum(vacantes), 4) as ocupacion,
                   count(*) filter (where categoria = 'Baja demanda') as baja_demanda,
                   count(*) filter (where categoria = 'Llena') as llenas
            from marts.mart_ocupacion_secciones
            where periodo = ?
            group by sede, turno
        """, [periodo])

    def ocupacion_por_modalidad(self) -> pd.DataFrame:
        return self.df("""
            select periodo, modalidad, count(*) as secciones,
                   sum(inscritos_cierre) as inscritos,
                   round(sum(inscritos_cierre) / sum(vacantes), 4) as ocupacion
            from marts.mart_ocupacion_secciones
            group by periodo, modalidad order by periodo, modalidad
        """)

    def secciones_baja_demanda(self, periodo: str) -> pd.DataFrame:
        return self.df("""
            select seccion_id, curso, sede, turno, vacantes, inscritos_cierre, ocupacion
            from marts.mart_ocupacion_secciones
            where periodo = ? and categoria = 'Baja demanda' and modalidad = 'Presencial'
            order by ocupacion, sede, turno
        """, [periodo])

    # ------------------------------------------------------------- retención

    def retencion(self) -> pd.DataFrame:
        return self.df("""
            select cohorte, periodos_desde_ingreso, ingresantes_matriculados, matriculados, tasa_retencion
            from marts.mart_retencion_cohortes order by cohorte, periodos_desde_ingreso
        """)

    def continuidad(self, por: str) -> pd.DataFrame:
        """Tasa de matrícula al ciclo siguiente según deuda o promedio (solo periodos con siguiente)."""
        segmentos = {
            "deuda": """case when cuotas_impagas = 0 then '0 cuotas'
                             when cuotas_impagas = 1 then '1 cuota'
                             when cuotas_impagas = 2 then '2 cuotas'
                             else '3 o más' end""",
            "promedio": """case when promedio_ponderado < 8 then 'menos de 8'
                                when promedio_ponderado < 11 then '8 a 10.9'
                                when promedio_ponderado < 14 then '11 a 13.9'
                                else '14 o más' end""",
        }
        return self.df(f"""
            select {segmentos[por]} as segmento,
                   count(*) as alumnos,
                   round(avg(se_matricula_siguiente::int), 4) as tasa_continua
            from marts.fct_matricula_alumno
            where se_matricula_siguiente is not null
              {"and promedio_ponderado is not null" if por == "promedio" else ""}
            group by 1 order by 1
        """)

    # ------------------------------------------------------------- cursos

    def cursos_filtro(self, n: int = 10, min_inscritos: int = 300) -> pd.DataFrame:
        return self.df("""
            select curso, tipo_curso, inscritos, tasa_retiro, tasa_desaprobacion, tasa_no_aprobacion, nota_promedio
            from marts.mart_cursos_filtro
            where inscritos >= ?
            order by tasa_no_aprobacion desc
            limit ?
        """, [min_inscritos, n])

    # ------------------------------------------------------------- calidad

    def calidad(self) -> pd.DataFrame:
        return self.df("select * from marts.mart_calidad_datos")

    def corridas(self, n: int = 10) -> pd.DataFrame:
        try:
            return self.df("select * from auditoria.corridas order by fecha desc limit ?", [n])
        except duckdb.CatalogException:
            return pd.DataFrame()

    def resultados_tests(self) -> pd.DataFrame:
        try:
            return self.df("""
                select nombre, tipo, estado, segundos, filas
                from auditoria.resultados where tipo in ('test', 'test unitario')
                order by case estado when 'fail' then 0 when 'error' then 0 when 'warn' then 1 else 2 end, nombre
            """)
        except duckdb.CatalogException:
            return pd.DataFrame()
