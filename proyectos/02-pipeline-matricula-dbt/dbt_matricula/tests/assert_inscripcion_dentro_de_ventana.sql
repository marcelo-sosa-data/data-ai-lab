-- Toda inscripción tiene que caer entre la apertura de la matrícula y el
-- fin de la extemporánea de su periodo.
select i.id_inscripcion, i.periodo, i.fecha_inscripcion
from {{ ref('fct_inscripciones') }} as i
inner join {{ ref('calendario_academico') }} as c on c.periodo = i.periodo
where cast(i.fecha_inscripcion as date) not between c.inicio_matricula and c.fin_extemporanea
