-- Curva de avance: cuántos alumnos llevan matrícula al día N desde que se
-- abrió el proceso. Sirve para comparar el periodo en curso contra el mismo
-- día de periodos anteriores.
with calendario as (
    select periodo, inicio_matricula, inicio_clases,
           date_diff('day', inicio_matricula, fin_extemporanea) as ultimo_dia
    from {{ ref('calendario_academico') }}
    where periodo in (select distinct periodo from {{ ref('fct_matricula_alumno') }})
),

dias as (
    select c.periodo, d.dia, c.inicio_matricula + d.dia::integer as fecha,
           c.inicio_matricula + d.dia::integer >= c.inicio_clases as es_extemporanea
    from calendario as c
    cross join range(0, 28) as d(dia)
    where d.dia <= c.ultimo_dia
),

por_dia as (
    select
        periodo,
        dia_matricula as dia,
        count(*) as matriculados,
        count(*) filter (where es_ingresante) as ingresantes
    from {{ ref('fct_matricula_alumno') }}
    group by periodo, dia_matricula
)

select
    d.periodo,
    d.dia,
    d.fecha,
    d.es_extemporanea,
    coalesce(p.matriculados, 0) as matriculados_dia,
    sum(coalesce(p.matriculados, 0)) over w as matriculados_acumulados,
    sum(coalesce(p.ingresantes, 0)) over w as ingresantes_acumulados,
    round(sum(coalesce(p.matriculados, 0)) over w
          / sum(coalesce(p.matriculados, 0)) over (partition by d.periodo), 4) as pct_del_total
from dias as d
left join por_dia as p on p.periodo = d.periodo and p.dia = d.dia
window w as (partition by d.periodo order by d.dia rows between unbounded preceding and current row)
