-- severidad: error
-- descripcion: Todo ingreso tiene fecha de resultado posterior a la inscripción, y en el examen también puntaje
SELECT campania, modalidad, count(*) AS filas
FROM inscripciones
WHERE estado = 'Ingresó'
  AND (fecha_resultado IS NULL
       OR fecha_resultado::DATE < fecha_inscripcion::DATE
       OR (modalidad = 'Examen de admisión' AND puntaje IS NULL))
GROUP BY ALL
