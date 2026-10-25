-- Una fila por alumno y periodo en que se matriculó: carga, retiros, notas y deuda.
-- La deuda se mide al cierre del ciclo (o a la fecha de corte si el ciclo sigue abierto).
with inscripciones as (
    select i.*, cu.creditos, n.nota_final, n.es_nsp
    from {{ ref('int_inscripciones') }} as i
    inner join {{ ref('stg_cursos') }} as cu on cu.curso_cod = i.curso_cod
    left join {{ ref('stg_notas') }} as n
        on n.codigo_alumno = i.codigo_alumno and n.seccion_id = i.seccion_id
    where i.estado <> 'Cambio de sección'
),

carga as (
    select
        codigo_alumno,
        periodo,
        min(fecha_inscripcion) as fecha_matricula,
        arg_min(canal, fecha_inscripcion) as canal,
        count(*) as cursos_inscritos,
        sum(creditos) as creditos_inscritos,
        count(*) filter (where estado = 'Retirado') as cursos_retirados,
        coalesce(sum(creditos) filter (where estado = 'Retirado'), 0) as creditos_retirados,
        sum(nota_final * creditos) filter (where nota_final is not null)
            / nullif(sum(creditos) filter (where nota_final is not null), 0) as promedio_ponderado,
        coalesce(sum(creditos) filter (where nota_final >= 11), 0) as creditos_aprobados,
        count(*) filter (where es_nsp) as cursos_nsp
    from inscripciones
    group by codigo_alumno, periodo
),

calendario as (
    select
        *,
        least(fin_clases, cast('{{ var("fecha_corte") }}' as date)) as fecha_evaluacion_deuda,
        fin_clases < cast('{{ var("fecha_corte") }}' as date) as periodo_cerrado
    from {{ ref('calendario_academico') }}
),

deuda as (
    select
        p.codigo_alumno,
        p.periodo,
        count(*) filter (
            where p.cuota > 0
              and p.fecha_vencimiento <= c.fecha_evaluacion_deuda
              and (p.fecha_pago is null or cast(p.fecha_pago as date) > c.fecha_evaluacion_deuda)
        ) as cuotas_impagas,
        coalesce(sum(p.monto) filter (
            where p.cuota > 0
              and p.fecha_vencimiento <= c.fecha_evaluacion_deuda
              and (p.fecha_pago is null or cast(p.fecha_pago as date) > c.fecha_evaluacion_deuda)
        ), 0) as deuda_vencida
    from {{ ref('stg_pagos') }} as p
    inner join calendario as c on c.periodo = p.periodo
    group by p.codigo_alumno, p.periodo
)

select
    k.codigo_alumno,
    k.periodo,
    k.fecha_matricula,
    date_diff('day', c.inicio_matricula, cast(k.fecha_matricula as date)) as dia_matricula,
    cast(k.fecha_matricula as date) >= c.inicio_clases as matricula_extemporanea,
    k.canal,
    k.cursos_inscritos,
    k.creditos_inscritos,
    k.cursos_retirados,
    k.creditos_retirados,
    k.cursos_retirados = k.cursos_inscritos as retiro_total,
    round(k.promedio_ponderado, 2) as promedio_ponderado,
    k.creditos_aprobados,
    k.cursos_nsp,
    coalesce(d.cuotas_impagas, 0) as cuotas_impagas,
    coalesce(d.deuda_vencida, 0) as deuda_vencida,
    c.periodo_cerrado
from carga as k
inner join calendario as c on c.periodo = k.periodo
left join deuda as d on d.codigo_alumno = k.codigo_alumno and d.periodo = k.periodo
