-- severidad: error
-- descripcion: Un código de postulante pertenece a un solo documento en todas sus versiones
SELECT campania, codigo_postulante, count(DISTINCT documento) AS documentos
FROM stg_inscripciones
WHERE NOT es_prueba
GROUP BY ALL
HAVING count(DISTINCT documento) > 1
