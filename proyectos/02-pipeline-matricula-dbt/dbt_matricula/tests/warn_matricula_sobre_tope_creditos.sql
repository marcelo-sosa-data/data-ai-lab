-- El reglamento pone un tope de créditos por ciclo. Hay excepciones con
-- autorización del director de carrera, así que esto avisa, no detiene.
{{ config(severity='warn') }}

select codigo_alumno, periodo, creditos_inscritos
from {{ ref('fct_matricula_alumno') }}
where excede_tope_creditos
