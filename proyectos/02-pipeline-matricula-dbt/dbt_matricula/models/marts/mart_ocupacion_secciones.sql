-- Ocupación de cada sección al cierre de la matrícula extemporánea, que es
-- cuando la universidad decide si cierra o fusiona secciones.
with inscritos as (
    select
        i.seccion_id,
        count(*) filter (
            where cast(i.fecha_inscripcion as date) <= c.fin_extemporanea
              and (i.fecha_retiro is null or cast(i.fecha_retiro as date) > c.fin_extemporanea)
        ) as inscritos_cierre,
        count(*) filter (where i.estado = 'Retirado') as retirados,
        count(*) filter (where i.estado = 'Vigente') as vigentes
    from {{ ref('int_inscripciones') }} as i
    inner join {{ ref('calendario_academico') }} as c on c.periodo = i.periodo
    group by i.seccion_id
)

select
    s.seccion_id,
    s.periodo,
    s.curso_cod,
    cu.curso,
    s.sede,
    s.turno,
    s.modalidad,
    s.vacantes,
    coalesce(i.inscritos_cierre, 0) as inscritos_cierre,
    coalesce(i.vigentes, 0) as vigentes,
    coalesce(i.retirados, 0) as retirados,
    round(coalesce(i.inscritos_cierre, 0) / s.vacantes, 4) as ocupacion,
    case
        when coalesce(i.inscritos_cierre, 0) >= s.vacantes then 'Llena'
        when coalesce(i.inscritos_cierre, 0) / s.vacantes < {{ var('umbral_baja_ocupacion') }} then 'Baja demanda'
        else 'Normal'
    end as categoria
from {{ ref('dim_secciones') }} as s
inner join {{ ref('dim_cursos') }} as cu on cu.curso_cod = s.curso_cod
left join inscritos as i on i.seccion_id = s.seccion_id
