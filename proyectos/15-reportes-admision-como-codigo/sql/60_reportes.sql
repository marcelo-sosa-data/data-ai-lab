-- Tablas que lee el sitio. Todo se calcula al corte de cada campaña.

CREATE OR REPLACE TABLE kpi_campania AS
WITH leads AS (
    SELECT campania, count(*) AS interesados FROM interesados GROUP BY campania
)
SELECT
    c.codigo                                          AS campania,
    c.corte,
    c.semana_corte,
    coalesce(l.interesados, 0)                        AS interesados,
    count(p.clave_persona)                            AS postulantes,
    coalesce(sum(p.n_inscripciones), 0)               AS inscripciones,
    count(*) FILTER (WHERE p.ingreso)                 AS ingresantes,
    count(*) FILTER (WHERE p.ingreso AND p.matriculado) AS matriculados,
    count(*) FILTER (WHERE p.ingreso AND NOT p.matriculado) AS pendientes_matricula,
    count(*) FILTER (WHERE p.n_inscripciones > 1)     AS postulantes_varias_inscripciones
FROM campanias AS c
LEFT JOIN postulantes AS p ON p.campania = c.codigo
LEFT JOIN leads AS l ON l.campania = c.codigo
GROUP BY ALL
ORDER BY c.codigo;

-- Embudo por modalidad, contado por inscripción: una persona que dio el examen
-- dos veces aporta dos inscripciones y, si ingresó, un solo ingreso.
CREATE OR REPLACE TABLE embudo_modalidad AS
SELECT
    i.campania,
    i.modalidad,
    count(*) FILTER (WHERE i.estado <> 'Anulado')                       AS inscripciones,
    count(*) FILTER (WHERE i.estado IN ('Ingresó', 'No ingresó'))       AS evaluadas,
    count(*) FILTER (WHERE p.codigo_ingreso = i.codigo_postulante)      AS ingresos,
    count(*) FILTER (WHERE p.codigo_ingreso = i.codigo_postulante AND p.matriculado) AS matriculas
FROM inscripciones AS i
LEFT JOIN postulantes AS p USING (campania, clave_persona)
GROUP BY ALL
ORDER BY i.campania, inscripciones DESC;

CREATE OR REPLACE TABLE embudo_sede_carrera AS
WITH base AS (
    SELECT c.codigo AS campania, s.sede, k.carrera
    FROM campanias AS c, (SELECT DISTINCT sede FROM catalogo_sedes) AS s, (SELECT DISTINCT carrera FROM catalogo_carreras) AS k
),
pos AS (
    SELECT campania, sede, carrera,
           count(*) AS postulantes,
           count(*) FILTER (WHERE ingreso) AS ingresantes,
           count(*) FILTER (WHERE ingreso AND matriculado) AS matriculados
    FROM postulantes GROUP BY ALL
),
lea AS (
    SELECT campania, sede, carrera, count(*) AS interesados FROM interesados GROUP BY ALL
)
SELECT
    b.campania, b.sede, b.carrera,
    coalesce(l.interesados, 0)  AS interesados,
    coalesce(p.postulantes, 0)  AS postulantes,
    coalesce(p.ingresantes, 0)  AS ingresantes,
    coalesce(p.matriculados, 0) AS matriculados,
    v.vacantes,
    coalesce(p.matriculados, 0) / nullif(v.vacantes, 0) AS pct_vacantes_cubiertas
FROM base AS b
LEFT JOIN pos AS p USING (campania, sede, carrera)
LEFT JOIN lea AS l USING (campania, sede, carrera)
LEFT JOIN stg_vacantes AS v USING (campania, sede, carrera)
ORDER BY b.campania, b.sede, b.carrera;

-- Avance acumulado por semana de campaña, hasta la semana del corte.
CREATE OR REPLACE TABLE avance_semanal AS
WITH semanas AS (
    SELECT c.codigo AS campania, s.semana, c.inicio + to_days(7 * s.semana - 1) AS fin_semana
    FROM campanias AS c, LATERAL range(1, c.semana_corte + 1) AS s(semana)
),
nuevos AS (
    SELECT s.campania, s.semana, s.fin_semana,
        (SELECT count(*) FROM postulantes p WHERE p.campania = s.campania AND p.semana_inscripcion = s.semana) AS postulantes,
        (SELECT count(*) FROM postulantes p WHERE p.campania = s.campania AND p.ingreso AND p.semana_ingreso = s.semana) AS ingresantes,
        (SELECT count(*) FROM postulantes p WHERE p.campania = s.campania AND p.ingreso AND p.matriculado AND p.semana_matricula = s.semana) AS matriculados,
        (SELECT count(*) FROM interesados i WHERE i.campania = s.campania AND i.semana_registro = s.semana) AS interesados
    FROM semanas AS s
)
SELECT
    *,
    sum(postulantes)  OVER w AS postulantes_acum,
    sum(ingresantes)  OVER w AS ingresantes_acum,
    sum(matriculados) OVER w AS matriculados_acum
FROM nuevos
WINDOW w AS (PARTITION BY campania ORDER BY semana)
ORDER BY campania, semana;

-- La campaña en curso contra la comparable a la misma semana.
CREATE OR REPLACE TABLE comparativo AS
WITH par AS (
    SELECT codigo AS actual, anterior_comparable AS anterior, semana_corte
    FROM campanias WHERE codigo = (SELECT campania_actual FROM parametros)
),
marcado AS (
    SELECT
        p.*,
        CASE WHEN p.campania = par.actual THEN 'actual' ELSE 'anterior' END AS cual
    FROM postulantes AS p, par
    WHERE p.campania IN (par.actual, par.anterior)
      AND p.semana_inscripcion <= par.semana_corte
),
largo AS (
    SELECT 'Total' AS dimension, 'Total' AS valor, cual FROM marcado
    UNION ALL SELECT 'Sede', sede, cual FROM marcado
    UNION ALL SELECT 'Modalidad', modalidad_primera, cual FROM marcado
    UNION ALL SELECT 'Carrera', carrera, cual FROM marcado
)
SELECT
    dimension, valor,
    count(*) FILTER (WHERE cual = 'actual')   AS actual,
    count(*) FILTER (WHERE cual = 'anterior') AS anterior,
    count(*) FILTER (WHERE cual = 'actual') / nullif(count(*) FILTER (WHERE cual = 'anterior'), 0) - 1 AS variacion
FROM largo
GROUP BY dimension, valor
ORDER BY CASE dimension WHEN 'Total' THEN 0 WHEN 'Sede' THEN 1 WHEN 'Modalidad' THEN 2 ELSE 3 END, actual DESC;

CREATE OR REPLACE TABLE canales AS
SELECT
    i.campania,
    i.canal,
    count(*)                                              AS interesados,
    count(*) FILTER (WHERE i.clave_persona IS NOT NULL)   AS postulantes,
    count(*) FILTER (WHERE p.ingreso)                     AS ingresantes,
    count(*) FILTER (WHERE p.ingreso AND p.matriculado)   AS matriculados,
    count(*) FILTER (WHERE i.clave_persona IS NOT NULL) / count(*) AS tasa_conversion
FROM interesados AS i
LEFT JOIN postulantes AS p USING (campania, clave_persona)
GROUP BY ALL
ORDER BY i.campania, tasa_conversion DESC;

-- Lista de llamadas: ingresantes de la campaña en curso que no pagan matrícula.
CREATE OR REPLACE TABLE pendientes_matricula AS
SELECT
    p.codigo_ingreso AS codigo_postulante,
    p.nombre_completo,
    p.tipo_documento,
    p.documento,
    p.celular,
    p.modalidad_ingreso AS modalidad,
    p.carrera,
    p.sede,
    p.fecha_ingreso::DATE AS fecha_ingreso,
    date_diff('day', p.fecha_ingreso::DATE, c.corte) AS dias_sin_matricula
FROM postulantes AS p
JOIN campanias AS c ON c.codigo = p.campania
WHERE p.campania = (SELECT campania_actual FROM parametros)
  AND p.ingreso AND NOT p.matriculado
ORDER BY dias_sin_matricula DESC, p.sede, p.carrera;

-- Proyección simple de vacantes cubiertas al cierre: los matriculados de hoy
-- multiplicados por cuánto creció cada sede en la campaña comparable desde
-- esta misma semana hasta su cierre. Se calcula por sede porque por carrera
-- hay celdas con muy pocos matriculados a estas alturas.
CREATE OR REPLACE TABLE proyeccion_vacantes AS
WITH par AS (
    SELECT codigo AS actual, anterior_comparable AS anterior, semana_corte
    FROM campanias WHERE codigo = (SELECT campania_actual FROM parametros)
),
factor AS (
    SELECT
        p.sede,
        count(*) FILTER (WHERE p.ingreso AND p.matriculado) AS final_anterior,
        count(*) FILTER (WHERE p.ingreso AND p.matriculado AND p.semana_matricula <= par.semana_corte) AS misma_semana_anterior
    FROM postulantes AS p, par
    WHERE p.campania = par.anterior
    GROUP BY p.sede
)
SELECT
    e.sede,
    e.carrera,
    e.vacantes,
    e.matriculados,
    f.final_anterior / nullif(f.misma_semana_anterior, 0) AS factor_sede,
    round(e.matriculados * f.final_anterior / nullif(f.misma_semana_anterior, 0)) AS matriculados_proyectados,
    round(e.matriculados * f.final_anterior / nullif(f.misma_semana_anterior, 0)) / nullif(e.vacantes, 0) AS cobertura_proyectada
FROM embudo_sede_carrera AS e
JOIN par ON e.campania = par.actual
LEFT JOIN factor AS f USING (sede)
ORDER BY cobertura_proyectada;
