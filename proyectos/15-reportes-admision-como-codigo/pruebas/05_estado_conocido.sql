-- severidad: error
-- descripcion: El estado de cada inscripción es Inscrito, Anulado, Ingresó o No ingresó
SELECT campania, estado, count(*) AS filas
FROM stg_inscripciones
WHERE estado IS NULL OR estado NOT IN ('Inscrito', 'Anulado', 'Ingresó', 'No ingresó')
GROUP BY ALL
