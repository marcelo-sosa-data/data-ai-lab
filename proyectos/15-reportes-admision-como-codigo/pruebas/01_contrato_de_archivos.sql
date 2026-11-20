-- severidad: error
-- descripcion: Cada archivo llegó, tiene las columnas obligatorias y sus fechas se pueden leer en el formato acordado
SELECT campania, archivo, regla, detalle
FROM hallazgos_lectura
WHERE severidad = 'error'
