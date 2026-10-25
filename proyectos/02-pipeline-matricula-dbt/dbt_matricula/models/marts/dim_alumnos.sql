with primera as (
    select codigo_alumno, min(periodo) as primer_periodo_matriculado, count(*) as periodos_matriculados
    from {{ ref('int_alumno_periodo') }}
    group by codigo_alumno
)

select
    a.codigo_alumno,
    a.carrera_cod,
    c.carrera,
    c.facultad,
    a.sede,
    a.periodo_ingreso as cohorte,
    a.modalidad_ingreso,
    a.genero,
    date_diff('year', a.fecha_nacimiento, cal.inicio_clases) as edad_ingreso,
    a.distrito,
    p.primer_periodo_matriculado,
    coalesce(p.periodos_matriculados, 0) as periodos_matriculados,
    p.codigo_alumno is not null as se_matriculo
from {{ ref('stg_alumnos') }} as a
inner join {{ ref('stg_carreras') }} as c on c.carrera_cod = a.carrera_cod
left join {{ ref('calendario_academico') }} as cal on cal.periodo = a.periodo_ingreso
left join primera as p on p.codigo_alumno = a.codigo_alumno
