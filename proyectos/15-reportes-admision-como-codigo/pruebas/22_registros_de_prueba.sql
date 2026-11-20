-- severidad: aviso
-- descripcion: Registros de prueba de sistemas que vinieron en el export y se excluyeron
SELECT campania, count(*) AS filas
FROM stg_inscripciones
WHERE es_prueba
GROUP BY campania
HAVING count(*) > 20
