-- En ningún momento una sección puede tener más alumnos que vacantes.
-- Se reconstruye la ocupación evento por evento (+1 inscripción, -1 retiro).
with movimientos as (
    select seccion_id, fecha_inscripcion as fecha_hora, 1 as delta
    from {{ ref('fct_inscripciones') }}
    union all
    select seccion_id, fecha_retiro, -1
    from {{ ref('fct_inscripciones') }}
    where fecha_retiro is not null
),

ocupacion as (
    select
        seccion_id,
        sum(delta) over (partition by seccion_id order by fecha_hora, delta
                         rows between unbounded preceding and current row) as inscritos
    from movimientos
)

select o.seccion_id, max(o.inscritos) as maximo, s.vacantes
from ocupacion as o
inner join {{ ref('dim_secciones') }} as s on s.seccion_id = o.seccion_id
group by o.seccion_id, s.vacantes
having max(o.inscritos) > s.vacantes
