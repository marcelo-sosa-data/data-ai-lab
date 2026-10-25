select seccion_id, periodo, curso_cod, sede, turno, modalidad, vacantes
from {{ ref('stg_secciones') }}
