{# Usa el nombre de schema tal cual (staging, intermedio, marts) en vez de main_staging. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
