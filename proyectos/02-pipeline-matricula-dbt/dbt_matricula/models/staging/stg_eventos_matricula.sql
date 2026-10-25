-- Una fila por evento del log, con tipos limpios. No descarta nada:
-- las marcas (es_prueba, codigo_corregido, fecha_formato_ddmm) las usa
-- int_eventos_limpios para filtrar y mart_calidad_datos para contar.
select
    cast(id_evento as bigint) as id_evento,
    {{ limpiar_codigo('codigo_alumno') }} as codigo_alumno,
    trim(seccion_id) as seccion_id,
    case upper(trim(tipo))
        when 'INS' then 'INSCRIPCION'
        when 'RET' then 'RETIRO'
    end as tipo_evento,
    {{ parsear_fecha_hora('fecha_hora') }} as fecha_hora,
    trim(canal) as canal,
    trim(seccion_id) like 'PRB-%' as es_prueba,
    codigo_alumno <> {{ limpiar_codigo('codigo_alumno') }} as codigo_corregido,
    fecha_hora like '__/__/____%' as fecha_formato_ddmm
from {{ source('sistema_academico', 'eventos_matricula') }}
