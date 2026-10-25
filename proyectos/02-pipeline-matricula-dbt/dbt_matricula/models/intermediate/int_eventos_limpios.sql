{{
    config(
        materialized='incremental',
        unique_key='id_evento',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

-- Eventos de matrícula sin secciones de prueba y sin dobles clics.
--
-- Incremental: durante las tres semanas de matrícula el export se actualiza
-- varias veces al día. En cada corrida se reprocesan los últimos N días
-- (var dias_reproceso) y se reemplazan por id_evento. Para que un doble
-- clic que cae justo en el borde de la ventana no se escape, el lag mira
-- un minuto antes del inicio de la ventana.

{% set desde %}
    (select max(fecha_hora) - interval '{{ var("dias_reproceso") }} days' from {{ this }})
{% endset %}

with eventos as (
    select *
    from {{ ref('stg_eventos_matricula') }}
    where not es_prueba
    {% if is_incremental() %}
        and fecha_hora >= {{ desde }} - interval '1 minute'
    {% endif %}
),

con_anterior as (
    select
        *,
        lag(fecha_hora) over (
            partition by codigo_alumno, seccion_id, tipo_evento
            order by fecha_hora, id_evento
        ) as fecha_hora_anterior
    from eventos
)

select
    id_evento,
    codigo_alumno,
    seccion_id,
    tipo_evento,
    fecha_hora,
    canal,
    codigo_corregido,
    fecha_formato_ddmm
from con_anterior
where (
        fecha_hora_anterior is null
        or date_diff('second', fecha_hora_anterior, fecha_hora) > {{ var('ventana_doble_clic_seg') }}
    )
{% if is_incremental() %}
    and fecha_hora >= {{ desde }}
{% endif %}
