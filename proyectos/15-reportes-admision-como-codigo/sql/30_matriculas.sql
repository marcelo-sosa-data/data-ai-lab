-- Asigna cada pago de matrícula a una persona. Primero por el código de
-- postulante que viene en la referencia; si no hay, por el documento sin los
-- ceros que pierde tesorería. Lo que no cruza queda en pagos_sin_asignar.
CREATE OR REPLACE TABLE pagos_matricula AS
WITH pm AS (
    SELECT row_number() OVER (ORDER BY campania, fecha_pago, doc_sin_ceros) AS id_pago, *
    FROM stg_pagos
    WHERE tipo_pago = 'MATRICULA'
),
por_codigo AS (
    SELECT pm.id_pago, i.clave_persona, 'referencia' AS via
    FROM pm
    JOIN inscripciones AS i
      ON i.campania = pm.campania AND i.codigo_postulante = pm.referencia_codigo
),
por_documento AS (
    SELECT pm.id_pago, p.clave_persona, 'documento' AS via
    FROM pm
    JOIN personas AS p
      ON p.campania = pm.campania AND ltrim(p.documento, '0') = pm.doc_sin_ceros
    WHERE pm.id_pago NOT IN (SELECT id_pago FROM por_codigo)
    QUALIFY count(*) OVER (PARTITION BY pm.id_pago) = 1
),
asignados AS (
    SELECT * FROM por_codigo
    UNION ALL
    SELECT * FROM por_documento
)
SELECT pm.*, a.clave_persona, coalesce(a.via, 'sin asignar') AS via
FROM pm
LEFT JOIN asignados AS a USING (id_pago);

CREATE OR REPLACE TABLE matriculas AS
SELECT
    campania,
    clave_persona,
    min(fecha_pago)     AS fecha_matricula,
    arg_min(via, fecha_pago) AS via,
    count(*)            AS n_pagos,
    sum(monto)          AS monto
FROM pagos_matricula
WHERE clave_persona IS NOT NULL
GROUP BY campania, clave_persona;

CREATE OR REPLACE TABLE pagos_sin_asignar AS
SELECT campania, fecha_pago, documento_pagador, pagador, concepto, monto
FROM pagos_matricula
WHERE via = 'sin asignar';
