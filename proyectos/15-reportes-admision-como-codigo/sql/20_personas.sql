-- Una fila por persona y campaña. Postulante es quien tiene al menos una
-- inscripción no anulada, aunque se haya inscrito en dos modalidades o haya
-- vuelto a dar el examen. Ingresante es quien ingresó por cualquiera de ellas.
CREATE OR REPLACE TABLE personas AS
WITH validas AS (
    SELECT * FROM inscripciones WHERE estado <> 'Anulado'
),
primera AS (
    SELECT
        campania,
        clave_persona,
        any_value(tipo_documento)                           AS tipo_documento,
        any_value(documento)                                AS documento,
        arg_max(nombre_completo, fecha_actualizacion)       AS nombre_completo,
        arg_max(celular, fecha_actualizacion)               AS celular,
        min(fecha_inscripcion)                              AS fecha_primera_inscripcion,
        arg_min(codigo_postulante, fecha_inscripcion)       AS codigo_primera,
        arg_min(modalidad, fecha_inscripcion)               AS modalidad_primera,
        arg_min(carrera, fecha_inscripcion)                 AS carrera_primera,
        arg_min(sede, fecha_inscripcion)                    AS sede_primera,
        count(*)                                            AS n_inscripciones,
        count(DISTINCT modalidad)                           AS n_modalidades
    FROM validas
    GROUP BY campania, clave_persona
),
ingreso AS (
    SELECT
        campania,
        clave_persona,
        arg_min(codigo_postulante, fecha_resultado) AS codigo_ingreso,
        arg_min(modalidad, fecha_resultado)         AS modalidad_ingreso,
        arg_min(carrera, fecha_resultado)           AS carrera_ingreso,
        arg_min(sede, fecha_resultado)              AS sede_ingreso,
        min(fecha_resultado)                        AS fecha_ingreso
    FROM validas
    WHERE estado = 'Ingresó'
    GROUP BY campania, clave_persona
)
SELECT
    p.*,
    coalesce(i.carrera_ingreso, p.carrera_primera) AS carrera,
    coalesce(i.sede_ingreso, p.sede_primera)       AS sede,
    i.codigo_ingreso,
    i.modalidad_ingreso,
    i.fecha_ingreso,
    i.codigo_ingreso IS NOT NULL                   AS ingreso
FROM primera AS p
LEFT JOIN ingreso AS i USING (campania, clave_persona);
