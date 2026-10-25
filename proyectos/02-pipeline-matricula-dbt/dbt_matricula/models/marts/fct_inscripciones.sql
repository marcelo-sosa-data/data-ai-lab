-- Una fila por alumno y sección, con el resultado del curso si el periodo ya cerró.
select
    i.id_inscripcion,
    i.codigo_alumno,
    i.seccion_id,
    i.periodo,
    i.curso_cod,
    i.fecha_inscripcion,
    i.fecha_retiro,
    i.estado,
    i.tipo_matricula,
    i.canal,
    n.nota_final,
    coalesce(n.es_nsp, false) as es_nsp,
    case when n.nota_final is not null then n.nota_final >= 11 end as aprobado
from {{ ref('int_inscripciones') }} as i
left join {{ ref('stg_notas') }} as n
    on n.codigo_alumno = i.codigo_alumno and n.seccion_id = i.seccion_id
