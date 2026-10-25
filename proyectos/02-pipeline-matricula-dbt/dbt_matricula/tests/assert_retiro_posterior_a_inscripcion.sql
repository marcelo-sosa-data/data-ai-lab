select id_inscripcion, fecha_inscripcion, fecha_retiro
from {{ ref('fct_inscripciones') }}
where fecha_retiro < fecha_inscripcion
