select curso_cod, curso, creditos, tipo_curso
from {{ ref('stg_cursos') }}
