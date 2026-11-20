-- severidad: error
-- descripcion: La última semana de la campaña en curso trae al menos 40% del promedio de las cuatro anteriores en postulantes y leads
WITH a AS (
    SELECT s.*, c.semana_corte
    FROM avance_semanal AS s
    JOIN campanias AS c ON c.codigo = s.campania
    WHERE s.campania = (SELECT campania_actual FROM parametros)
),
comparado AS (
    SELECT
        'postulantes' AS medida,
        max(postulantes) FILTER (WHERE semana = semana_corte) AS ultima,
        avg(postulantes) FILTER (WHERE semana BETWEEN semana_corte - 4 AND semana_corte - 1) AS promedio_4
    FROM a
    UNION ALL
    SELECT
        'interesados',
        max(interesados) FILTER (WHERE semana = semana_corte),
        avg(interesados) FILTER (WHERE semana BETWEEN semana_corte - 4 AND semana_corte - 1)
    FROM a
)
SELECT medida, ultima, round(promedio_4, 1) AS promedio_4
FROM comparado
WHERE coalesce(ultima, 0) < 0.4 * promedio_4
