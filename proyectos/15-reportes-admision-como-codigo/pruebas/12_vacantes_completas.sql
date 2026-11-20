-- severidad: error
-- descripcion: Toda carrera y sede con postulantes tiene vacantes cargadas
SELECT campania, sede, carrera, postulantes
FROM embudo_sede_carrera
WHERE postulantes > 0 AND vacantes IS NULL
