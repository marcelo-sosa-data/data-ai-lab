select id_inscripcion, estado, nota_final
from {{ ref('fct_inscripciones') }}
where estado <> 'Vigente' and nota_final is not null
