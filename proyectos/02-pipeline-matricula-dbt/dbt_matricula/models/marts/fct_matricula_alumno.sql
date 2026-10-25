-- Una fila por alumno y periodo matriculado. Es la tabla base para medir
-- retención y para el modelo de alerta temprana (proyecto 03).
with base as (
    select
        ap.*,
        a.carrera,
        a.facultad,
        a.sede,
        a.cohorte,
        ap.periodo = a.cohorte as es_ingresante,
        {{ indice_periodo('ap.periodo') }} - {{ indice_periodo('a.cohorte') }} as periodos_desde_ingreso,
        {{ indice_periodo('ap.periodo') }} as idx_periodo
    from {{ ref('int_alumno_periodo') }} as ap
    inner join {{ ref('dim_alumnos') }} as a on a.codigo_alumno = ap.codigo_alumno
),

ultimo as (
    select max(idx_periodo) as idx_ultimo from base
)

select
    b.codigo_alumno,
    b.periodo,
    b.carrera,
    b.facultad,
    b.sede,
    b.cohorte,
    b.es_ingresante,
    b.periodos_desde_ingreso,
    b.fecha_matricula,
    b.dia_matricula,
    b.matricula_extemporanea,
    b.canal,
    b.cursos_inscritos,
    b.creditos_inscritos,
    b.creditos_inscritos > {{ var('max_creditos') }} as excede_tope_creditos,
    b.cursos_retirados,
    b.creditos_retirados,
    b.retiro_total,
    b.promedio_ponderado,
    b.creditos_aprobados,
    b.cursos_nsp,
    b.cuotas_impagas,
    b.deuda_vencida,
    b.periodo_cerrado,
    -- null cuando todavía no hay un periodo siguiente con datos
    case
        when b.idx_periodo = u.idx_ultimo then null
        else exists (
            select 1 from base as s
            where s.codigo_alumno = b.codigo_alumno and s.idx_periodo = b.idx_periodo + 1
        )
    end as se_matricula_siguiente
from base as b
cross join ultimo as u
