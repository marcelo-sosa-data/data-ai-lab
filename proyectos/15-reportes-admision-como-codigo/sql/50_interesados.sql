-- Leads del CRM. Primero se quitan las filas repetidas del export (mismo ID),
-- luego se junta a la misma persona registrada dos veces (mismo documento o
-- celular) y se queda el primer contacto, que es el que define el canal.
CREATE OR REPLACE TABLE interesados AS
WITH filas AS (
    SELECT * FROM stg_interesados
    QUALIFY row_number() OVER (PARTITION BY campania, id_lead ORDER BY fecha_registro) = 1
),
con_clave AS (
    SELECT *, coalesce('D' || ltrim(documento, '0'), 'C' || celular, 'L' || id_lead) AS clave_lead
    FROM filas
),
unicos AS (
    SELECT * FROM con_clave
    QUALIFY row_number() OVER (PARTITION BY campania, clave_lead ORDER BY fecha_registro, id_lead) = 1
),
por_documento AS (
    SELECT u.campania, u.id_lead, any_value(p.clave_persona) AS clave_persona
    FROM unicos AS u
    JOIN postulantes AS p
      ON p.campania = u.campania AND ltrim(p.documento, '0') = ltrim(u.documento, '0')
    GROUP BY ALL
),
por_celular AS (
    SELECT u.campania, u.id_lead, any_value(p.clave_persona) AS clave_persona
    FROM unicos AS u
    JOIN postulantes AS p ON p.campania = u.campania AND p.celular = u.celular
    WHERE u.id_lead NOT IN (SELECT id_lead FROM por_documento)
    GROUP BY ALL
)
SELECT
    u.campania, u.id_lead, u.clave_lead, u.fecha_registro, u.canal, u.carrera, u.sede,
    coalesce(d.clave_persona, c.clave_persona) AS clave_persona,
    date_diff('day', ca.inicio, u.fecha_registro::DATE) // 7 + 1 AS semana_registro
FROM unicos AS u
JOIN campanias AS ca ON ca.codigo = u.campania
LEFT JOIN por_documento AS d USING (campania, id_lead)
LEFT JOIN por_celular AS c USING (campania, id_lead);

-- Un postulante puede cruzar con dos leads distintos (uno por documento y otro
-- por celular); para el canal vale el primero.
CREATE OR REPLACE TABLE canal_postulante AS
SELECT campania, clave_persona, arg_min(canal, fecha_registro) AS canal
FROM interesados
WHERE clave_persona IS NOT NULL
GROUP BY ALL;
