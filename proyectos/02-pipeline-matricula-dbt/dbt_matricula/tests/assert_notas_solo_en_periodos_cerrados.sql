-- Un periodo en curso no puede tener notas finales; si aparecen, el export
-- se cruzó con otro periodo o la fecha de corte está mal.
select i.id_inscripcion, i.periodo, i.nota_final
from {{ ref('fct_inscripciones') }} as i
inner join {{ ref('calendario_academico') }} as c on c.periodo = i.periodo
where i.nota_final is not null
  and c.fin_clases >= cast('{{ var("fecha_corte") }}' as date)
