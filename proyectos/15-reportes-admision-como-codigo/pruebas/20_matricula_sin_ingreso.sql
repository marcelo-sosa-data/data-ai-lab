-- severidad: aviso
-- descripcion: Pagos de matrícula asignados a alguien que no figura como ingresante
SELECT m.campania, m.clave_persona, m.fecha_matricula
FROM matriculas AS m
JOIN personas AS p USING (campania, clave_persona)
WHERE NOT p.ingreso
