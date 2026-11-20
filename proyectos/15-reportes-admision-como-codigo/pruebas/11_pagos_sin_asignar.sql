-- severidad: error
-- descripcion: No más de 8% de los pagos de matrícula de una campaña se quedan sin persona asignada
SELECT campania,
       count(*) FILTER (WHERE via = 'sin asignar') AS sin_asignar,
       count(*) AS pagos,
       round(count(*) FILTER (WHERE via = 'sin asignar') / count(*), 4) AS proporcion
FROM pagos_matricula
GROUP BY campania
HAVING count(*) FILTER (WHERE via = 'sin asignar') > 0.08 * count(*)
