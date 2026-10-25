{# Códigos de alumno: el export trae minúsculas y espacios ("u202400123 ", " U202400123"). #}
{% macro limpiar_codigo(col) -%}
    upper(replace(trim({{ col }}), ' ', ''))
{%- endmacro %}

{# Ventanilla graba dd/mm/yyyy hh:mm; la web y la app, ISO. #}
{% macro parsear_fecha_hora(col) -%}
    coalesce(
        try_strptime(trim({{ col }}), '%Y-%m-%d %H:%M:%S'),
        try_strptime(trim({{ col }}), '%d/%m/%Y %H:%M')
    )
{%- endmacro %}

{# "S/ 1,250.00" -> 1250.00 #}
{% macro parsear_monto(col) -%}
    try_cast(regexp_replace(trim({{ col }}), '(S/|,|\s)', '', 'g') as decimal(10, 2))
{%- endmacro %}

{# 'LIMA NORTE', 'lima norte ', 'Lima  Norte' -> 'Lima Norte' #}
{% macro normalizar_sede(col) -%}
    case regexp_replace(lower(trim({{ col }})), '\s+', ' ', 'g')
        when 'lima norte' then 'Lima Norte'
        when 'lima centro' then 'Lima Centro'
        when 'arequipa' then 'Arequipa'
    end
{%- endmacro %}

{# '2025-2' -> 4051: permite restar periodos (2026-1 menos 2025-1 = 2) #}
{% macro indice_periodo(col) -%}
    (cast(left({{ col }}, 4) as integer) * 2 + cast(right({{ col }}, 1) as integer) - 1)
{%- endmacro %}
