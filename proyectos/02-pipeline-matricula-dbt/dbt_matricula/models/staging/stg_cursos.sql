select
    upper(trim(curso_cod)) as curso_cod,
    trim(curso) as curso,
    cast(creditos as integer) as creditos,
    trim(tipo) as tipo_curso
from {{ source('sistema_academico', 'cursos') }}
