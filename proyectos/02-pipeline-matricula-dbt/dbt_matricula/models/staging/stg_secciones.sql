select
    trim(seccion_id) as seccion_id,
    trim(periodo) as periodo,
    upper(trim(curso_cod)) as curso_cod,
    case upper(trim(sede))
        when 'LN' then 'Lima Norte'
        when 'LC' then 'Lima Centro'
        when 'AQ' then 'Arequipa'
        when 'VIR' then 'Virtual'
    end as sede,
    case upper(trim(turno))
        when 'M' then 'Mañana'
        when 'T' then 'Tarde'
        when 'N' then 'Noche'
    end as turno,
    trim(modalidad) as modalidad,
    cast(vacantes as integer) as vacantes
from {{ source('sistema_academico', 'secciones') }}
