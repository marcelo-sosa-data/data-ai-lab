select
    upper(trim(carrera_cod)) as carrera_cod,
    upper(trim(curso_cod)) as curso_cod,
    cast(ciclo as integer) as ciclo
from {{ source('sistema_academico', 'plan_estudios') }}
