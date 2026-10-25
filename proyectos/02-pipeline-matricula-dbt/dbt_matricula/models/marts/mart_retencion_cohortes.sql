-- Retención por cohorte: de los ingresantes que se matricularon en su
-- primer periodo, qué porcentaje sigue matriculado k periodos después.
-- La base son los que se matricularon, no los admitidos: un admitido que
-- nunca llegó a matricularse es un problema de admisión, no de retención.
with matriculas as (
    select codigo_alumno, cohorte, periodos_desde_ingreso
    from {{ ref('fct_matricula_alumno') }}
),

base as (
    select cohorte, count(*) as ingresantes_matriculados
    from matriculas
    where periodos_desde_ingreso = 0
    group by cohorte
),

limites as (
    select max({{ indice_periodo('periodo') }}) as idx_ultimo from {{ ref('fct_matricula_alumno') }}
),

rejilla as (
    select b.cohorte, k.k as periodos_desde_ingreso, b.ingresantes_matriculados
    from base as b
    cross join range(0, 12) as k(k)
    cross join limites as l
    where {{ indice_periodo('b.cohorte') }} + k.k <= l.idx_ultimo
)

select
    r.cohorte,
    r.periodos_desde_ingreso,
    r.ingresantes_matriculados,
    count(m.codigo_alumno) as matriculados,
    round(count(m.codigo_alumno) / r.ingresantes_matriculados, 4) as tasa_retencion
from rejilla as r
left join matriculas as m
    on m.cohorte = r.cohorte
   and m.periodos_desde_ingreso = r.periodos_desde_ingreso
   and exists (
       select 1 from matriculas as m0
       where m0.codigo_alumno = m.codigo_alumno and m0.periodos_desde_ingreso = 0
   )
where r.cohorte >= (select min(periodo) from {{ ref('fct_matricula_alumno') }})
group by r.cohorte, r.periodos_desde_ingreso, r.ingresantes_matriculados
