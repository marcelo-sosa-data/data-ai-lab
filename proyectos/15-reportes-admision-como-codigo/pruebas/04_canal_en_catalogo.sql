-- severidad: error
-- descripcion: Cada lead tiene un canal del catálogo de Marketing
SELECT campania, canal, count(*) AS filas
FROM stg_interesados
WHERE canal IS NULL OR canal NOT IN (SELECT canal FROM catalogo_canales)
GROUP BY ALL
