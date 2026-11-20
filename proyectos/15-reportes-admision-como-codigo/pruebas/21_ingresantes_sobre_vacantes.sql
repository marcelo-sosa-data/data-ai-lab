-- severidad: aviso
-- descripcion: Carreras y sedes donde los matriculados ya pasan las vacantes
SELECT campania, sede, carrera, matriculados, vacantes
FROM embudo_sede_carrera
WHERE matriculados > vacantes
