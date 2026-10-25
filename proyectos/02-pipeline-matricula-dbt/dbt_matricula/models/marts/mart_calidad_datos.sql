-- Qué se corrigió, descartó o puso en cuarentena en cada corrida.
-- regla_id coincide con las llaves de datos/raw/_anomalias.json.
with eventos as (
    select
        count(*) as total,
        count(*) filter (where codigo_corregido) as codigos,
        count(*) filter (where fecha_formato_ddmm) as fechas,
        count(*) filter (where es_prueba) as prueba,
        count(*) filter (where not es_prueba) as no_prueba
    from {{ ref('stg_eventos_matricula') }}
),

pagos as (
    select count(*) as total, count(*) filter (where monto_con_formato) as montos
    from {{ ref('stg_pagos') }}
),

notas as (
    select count(*) as total, count(*) filter (where es_nsp) as nsp
    from {{ ref('stg_notas') }}
),

alumnos as (
    select
        (select count(*) from {{ source('sistema_academico', 'alumnos') }}) as total,
        (select count(*) from {{ ref('stg_alumnos') }}) as unicos
),

matriculas as (
    select count(*) as total, count(*) filter (where excede_tope_creditos) as sobre_tope
    from {{ ref('fct_matricula_alumno') }}
),

reglas as (
    select 'codigos_alumno_sucios' as regla_id, 'Código de alumno en minúsculas o con espacios' as regla,
           'eventos_matricula' as tabla, 'Corregido' as accion, codigos as registros, total from eventos
    union all
    select 'fechas_formato_ddmmyyyy', 'Fecha en formato dd/mm/yyyy (ventanilla)',
           'eventos_matricula', 'Corregido', fechas, total from eventos
    union all
    select 'eventos_secciones_prueba', 'Evento en sección de prueba (PRB-)',
           'eventos_matricula', 'Descartado', prueba, total from eventos
    union all
    select 'eventos_duplicados', 'Doble clic: evento repetido en menos de {{ var("ventana_doble_clic_seg") }} s',
           'eventos_matricula', 'Descartado',
           e.no_prueba - (select count(*) from {{ ref('int_eventos_limpios') }}), e.total
    from eventos as e
    union all
    select 'retiros_sin_inscripcion', 'Retiro sin inscripción previa',
           'eventos_matricula', 'En cuarentena',
           (select count(*) from {{ ref('int_retiros_sin_inscripcion') }}), total
    from eventos
    union all
    select 'alumnos_versiones_extra', 'Versión antigua del registro del alumno',
           'alumnos', 'Se conserva la última', total - unicos, total from alumnos
    union all
    select 'montos_con_formato_texto', 'Monto como texto ("S/ 1,250.00")',
           'pagos', 'Corregido', montos, total from pagos
    union all
    select 'notas_nsp', 'Nota NSP (no se presentó)',
           'notas', 'Se cuenta como 0', nsp, total from notas
    union all
    select 'matriculas_sobre_tope_creditos', 'Matrícula sobre el tope de {{ var("max_creditos") }} créditos',
           'fct_matricula_alumno', 'Marcado para revisión', sobre_tope, total from matriculas
)

select
    regla_id,
    regla,
    tabla,
    accion,
    registros,
    total as registros_tabla,
    round(registros / total, 4) as pct
from reglas
