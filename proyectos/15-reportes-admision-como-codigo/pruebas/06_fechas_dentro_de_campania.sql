-- severidad: error
-- descripcion: Inscripciones, resultados y pagos caen entre 30 días antes del inicio de la campaña y la fecha de corte
WITH fechas AS (
    SELECT 'inscripción' AS que, campania, fecha_inscripcion::DATE AS fecha FROM stg_inscripciones WHERE NOT es_prueba
    UNION ALL SELECT 'resultado', campania, fecha_resultado::DATE FROM stg_inscripciones WHERE NOT es_prueba AND fecha_resultado IS NOT NULL
    UNION ALL SELECT 'pago', campania, fecha_pago::DATE FROM stg_pagos
)
SELECT f.que, f.campania, min(f.fecha) AS desde, max(f.fecha) AS hasta, count(*) AS filas
FROM fechas AS f
JOIN campanias AS c ON c.codigo = f.campania
WHERE f.fecha IS NULL OR f.fecha < c.inicio - INTERVAL 30 DAY OR f.fecha > c.corte
GROUP BY ALL
