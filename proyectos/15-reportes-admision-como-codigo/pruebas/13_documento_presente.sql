-- severidad: error
-- descripcion: Toda inscripción tiene documento y un DNI tiene 8 dígitos
SELECT campania, tipo_documento, count(*) AS filas
FROM stg_inscripciones
WHERE NOT es_prueba
  AND (documento IS NULL OR (tipo_documento = 'DNI' AND NOT regexp_full_match(documento, '\d{8}')))
GROUP BY ALL
