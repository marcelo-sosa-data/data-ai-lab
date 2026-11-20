-- La tabla de personas con su matrícula y la semana de campaña de cada hito.
CREATE OR REPLACE TABLE postulantes AS
SELECT
    p.*,
    m.clave_persona IS NOT NULL                                        AS matriculado,
    m.fecha_matricula,
    m.via                                                              AS via_matricula,
    date_diff('day', c.inicio, p.fecha_primera_inscripcion::DATE) // 7 + 1 AS semana_inscripcion,
    date_diff('day', c.inicio, p.fecha_ingreso::DATE) // 7 + 1             AS semana_ingreso,
    date_diff('day', c.inicio, m.fecha_matricula::DATE) // 7 + 1           AS semana_matricula
FROM personas AS p
JOIN campanias AS c ON c.codigo = p.campania
LEFT JOIN matriculas AS m USING (campania, clave_persona);
