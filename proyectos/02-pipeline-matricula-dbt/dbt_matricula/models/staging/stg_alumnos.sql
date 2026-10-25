-- El maestro trae una fila por cada actualización: me quedo con la última.
with fuente as (
    select
        {{ limpiar_codigo('codigo_alumno') }} as codigo_alumno,
        upper(trim(carrera_cod)) as carrera_cod,
        {{ normalizar_sede('sede') }} as sede,
        trim(periodo_ingreso) as periodo_ingreso,
        trim(modalidad_ingreso) as modalidad_ingreso,
        cast(fecha_nacimiento as date) as fecha_nacimiento,
        upper(trim(genero)) as genero,
        trim(distrito) as distrito,
        cast(fecha_actualizacion as timestamp) as fecha_actualizacion
    from {{ source('sistema_academico', 'alumnos') }}
)

select *
from fuente
qualify row_number() over (partition by codigo_alumno order by fecha_actualizacion desc) = 1
