-- severidad: error
-- descripcion: Carreras y sedes de inscripciones, leads y vacantes existen en el catálogo
WITH valores AS (
    SELECT 'inscripciones' AS origen, campania, carrera, sede FROM stg_inscripciones WHERE NOT es_prueba
    UNION ALL SELECT 'interesados', campania, carrera, sede FROM stg_interesados
    UNION ALL SELECT 'vacantes', campania, carrera, sede FROM stg_vacantes
)
SELECT origen, campania, carrera, sede, count(*) AS filas
FROM valores
WHERE carrera IS NULL OR carrera NOT IN (SELECT carrera FROM catalogo_carreras)
   OR sede IS NULL OR sede NOT IN (SELECT sede FROM catalogo_sedes)
GROUP BY ALL
