-- Cursos que más alumnos dejan en el camino (retiro o desaprobación),
-- solo en periodos cerrados.
with inscripciones as (
    select i.*
    from {{ ref('fct_inscripciones') }} as i
    inner join {{ ref('calendario_academico') }} as c on c.periodo = i.periodo
    where i.estado <> 'Cambio de sección'
      and c.fin_clases < cast('{{ var("fecha_corte") }}' as date)
)

select
    i.curso_cod,
    c.curso,
    c.tipo_curso,
    count(*) as inscritos,
    count(*) filter (where i.estado = 'Retirado') as retirados,
    count(*) filter (where i.aprobado = false) as desaprobados,
    count(*) filter (where i.aprobado) as aprobados,
    round(avg(i.nota_final), 2) as nota_promedio,
    round(count(*) filter (where i.estado = 'Retirado') / count(*), 4) as tasa_retiro,
    round(count(*) filter (where i.aprobado = false) / count(*), 4) as tasa_desaprobacion,
    round(1 - count(*) filter (where i.aprobado) / count(*), 4) as tasa_no_aprobacion
from inscripciones as i
inner join {{ ref('dim_cursos') }} as c on c.curso_cod = i.curso_cod
group by i.curso_cod, c.curso, c.tipo_curso
