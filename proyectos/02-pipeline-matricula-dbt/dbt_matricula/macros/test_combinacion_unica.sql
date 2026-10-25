{# Lo mismo que dbt_utils.unique_combination_of_columns, sin depender de paquetes. #}
{% test combinacion_unica(model, columnas) %}
select {{ columnas | join(', ') }}, count(*) as repeticiones
from {{ model }}
group by {{ columnas | join(', ') }}
having count(*) > 1
{% endtest %}
