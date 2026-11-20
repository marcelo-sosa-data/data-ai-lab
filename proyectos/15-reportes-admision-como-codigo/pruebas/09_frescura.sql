-- severidad: error
-- descripcion: Los tres exports de la campaña en curso llegan hasta, como mucho, tres días antes del corte
WITH ultimo AS (
    SELECT 'admisión' AS fuente, max(fecha_inscripcion)::DATE AS hasta FROM stg_inscripciones
     WHERE campania = (SELECT campania_actual FROM parametros) AND NOT es_prueba
    UNION ALL
    SELECT 'crm', max(fecha_registro)::DATE FROM stg_interesados
     WHERE campania = (SELECT campania_actual FROM parametros)
    UNION ALL
    SELECT 'tesorería', max(fecha_pago)::DATE FROM stg_pagos
     WHERE campania = (SELECT campania_actual FROM parametros)
)
SELECT u.fuente, u.hasta, p.corte
FROM ultimo AS u, parametros AS p
WHERE u.hasta IS NULL OR u.hasta < p.corte - INTERVAL 3 DAY
