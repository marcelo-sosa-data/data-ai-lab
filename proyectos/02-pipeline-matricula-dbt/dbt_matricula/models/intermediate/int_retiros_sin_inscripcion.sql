-- Cuarentena: retiros de una sección en la que el alumno no tenía una
-- inscripción previa. Es un bug conocido del módulo antiguo de ventanilla.
-- No se borran: quedan aquí para que Registros Académicos los revise.
select r.*
from {{ ref('int_eventos_limpios') }} as r
where r.tipo_evento = 'RETIRO'
  and not exists (
      select 1
      from {{ ref('int_eventos_limpios') }} as i
      where i.tipo_evento = 'INSCRIPCION'
        and i.codigo_alumno = r.codigo_alumno
        and i.seccion_id = r.seccion_id
        and i.fecha_hora <= r.fecha_hora
  )
