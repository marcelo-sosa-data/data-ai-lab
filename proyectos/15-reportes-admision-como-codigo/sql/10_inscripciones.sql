-- Una fila por inscripción: la última versión que mandó el sistema y sin los
-- registros de prueba. El export repite la inscripción cada vez que se edita.
CREATE OR REPLACE TABLE inscripciones AS
SELECT * EXCLUDE (orden)
FROM (
    SELECT
        s.*,
        s.tipo_documento || '|' || s.documento AS clave_persona,
        row_number() OVER (
            PARTITION BY s.campania, s.codigo_postulante
            ORDER BY s.fecha_actualizacion DESC NULLS LAST, s.fila_archivo DESC
        ) AS orden
    FROM stg_inscripciones AS s
    WHERE NOT s.es_prueba
)
WHERE orden = 1;
