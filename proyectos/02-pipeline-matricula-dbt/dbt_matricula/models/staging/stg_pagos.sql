select
    {{ limpiar_codigo('codigo_alumno') }} as codigo_alumno,
    trim(periodo) as periodo,
    cast(cuota as integer) as cuota,
    cast(fecha_vencimiento as date) as fecha_vencimiento,
    cast(nullif(trim(fecha_pago), '') as timestamp) as fecha_pago,
    {{ parsear_monto('monto') }} as monto,
    monto like 'S/%' as monto_con_formato
from {{ source('sistema_academico', 'pagos') }}
