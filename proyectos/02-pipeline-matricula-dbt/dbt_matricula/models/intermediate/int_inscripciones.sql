-- Una fila por alumno y sección: cuándo se inscribió, si se retiró y en qué
-- estado quedó. Un retiro dentro de la ventana de matrícula seguido de otra
-- inscripción al mismo curso es un cambio de sección, no un retiro.
with eventos as (
    select * from {{ ref('int_eventos_limpios') }}
),

inscripciones as (
    select
        codigo_alumno,
        seccion_id,
        min(id_evento) as id_inscripcion,
        min(fecha_hora) as fecha_inscripcion,
        arg_min(canal, fecha_hora) as canal
    from eventos
    where tipo_evento = 'INSCRIPCION'
    group by codigo_alumno, seccion_id
),

retiros as (
    select codigo_alumno, seccion_id, max(fecha_hora) as fecha_retiro
    from eventos
    where tipo_evento = 'RETIRO'
    group by codigo_alumno, seccion_id
),

base as (
    select
        i.id_inscripcion,
        i.codigo_alumno,
        i.seccion_id,
        s.periodo,
        s.curso_cod,
        i.fecha_inscripcion,
        case when r.fecha_retiro >= i.fecha_inscripcion then r.fecha_retiro end as fecha_retiro,
        i.canal,
        case
            when cast(i.fecha_inscripcion as date) < c.inicio_clases then 'Regular'
            else 'Extemporánea'
        end as tipo_matricula,
        c.fin_extemporanea
    from inscripciones as i
    inner join {{ ref('stg_secciones') }} as s on s.seccion_id = i.seccion_id
    inner join {{ ref('calendario_academico') }} as c on c.periodo = s.periodo
    left join retiros as r on r.codigo_alumno = i.codigo_alumno and r.seccion_id = i.seccion_id
)

select
    b.id_inscripcion,
    b.codigo_alumno,
    b.seccion_id,
    b.periodo,
    b.curso_cod,
    b.fecha_inscripcion,
    b.fecha_retiro,
    case
        when b.fecha_retiro is null then 'Vigente'
        when cast(b.fecha_retiro as date) <= b.fin_extemporanea and exists (
            select 1 from base as otra
            where otra.codigo_alumno = b.codigo_alumno
              and otra.periodo = b.periodo
              and otra.curso_cod = b.curso_cod
              and otra.seccion_id <> b.seccion_id
              and otra.fecha_inscripcion >= b.fecha_inscripcion
        ) then 'Cambio de sección'
        else 'Retirado'
    end as estado,
    b.tipo_matricula,
    b.canal
from base as b
