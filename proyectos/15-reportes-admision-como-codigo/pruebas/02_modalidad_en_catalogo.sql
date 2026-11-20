-- severidad: error
-- descripcion: Toda inscripción tiene una modalidad del catálogo oficial
SELECT campania, modalidad, count(*) AS filas
FROM stg_inscripciones
WHERE NOT es_prueba
  AND (modalidad IS NULL OR modalidad NOT IN (SELECT modalidad FROM catalogo_modalidades))
GROUP BY ALL
