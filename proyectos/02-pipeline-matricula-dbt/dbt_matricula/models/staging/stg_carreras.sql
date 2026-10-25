select
    upper(trim(carrera_cod)) as carrera_cod,
    trim(carrera) as carrera,
    trim(facultad) as facultad
from {{ source('sistema_academico', 'carreras') }}
