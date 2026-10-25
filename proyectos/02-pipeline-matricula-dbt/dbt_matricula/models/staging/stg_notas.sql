-- NSP (no se presentó) cuenta como 0 en el promedio ponderado, como en el reglamento.
select
    {{ limpiar_codigo('codigo_alumno') }} as codigo_alumno,
    trim(seccion_id) as seccion_id,
    case when upper(trim(nota_final)) = 'NSP' then 0 else cast(nota_final as integer) end as nota_final,
    upper(trim(nota_final)) = 'NSP' as es_nsp
from {{ source('sistema_academico', 'notas') }}
