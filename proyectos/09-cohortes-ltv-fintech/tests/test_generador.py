import duckdb
import pandas as pd
import pytest
from generar_datos import FIN_OBSERVACION, LANZAMIENTO_SERVICIOS, generar


def test_misma_semilla_misma_base(tmp_path):
    a = generar(tmp_path / "a.duckdb", escala=0.02, seed=11)
    b = generar(tmp_path / "b.duckdb", escala=0.02, seed=11)
    q = "SELECT COUNT(*), ROUND(SUM(ingreso_neto), 4), ROUND(SUM(monto), 2) FROM transacciones"
    ca, cb = duckdb.connect(str(a)), duckdb.connect(str(b))
    assert ca.execute(q).fetchone() == cb.execute(q).fetchone()


def test_fechas_coherentes(con):
    malos = con.execute("""
        SELECT COUNT(*) FROM transacciones t JOIN clientes c USING (id_cliente)
        WHERE t.fecha_hora::DATE < c.fecha_activacion OR c.fecha_activacion IS NULL
           OR t.fecha_hora::DATE > ?
    """, [FIN_OBSERVACION]).fetchone()[0]
    assert malos == 0
    assert con.execute("SELECT COUNT(*) FROM clientes WHERE fecha_activacion < fecha_registro").fetchone()[0] == 0


def test_la_activacion_es_la_primera_transaccion(con):
    r = con.execute("""
        SELECT COUNT(*) FROM clientes c
        LEFT JOIN (SELECT id_cliente, MIN(fecha_hora)::DATE AS primera FROM transacciones GROUP BY 1) t
          USING (id_cliente)
        WHERE c.fecha_activacion IS NOT NULL AND t.primera IS DISTINCT FROM c.fecha_activacion
    """).fetchone()[0]
    assert r == 0


def test_ingreso_segun_tipo(con):
    r = con.execute("""
        SELECT tipo, MIN(ingreso_neto / monto) AS tasa_min, MAX(ingreso_neto / monto) AS tasa_max,
               MIN(ingreso_neto) AS minimo, MAX(ingreso_neto) AS maximo
        FROM transacciones GROUP BY tipo
    """).df().set_index("tipo")
    assert r.loc["Transferencia", "minimo"] == r.loc["Transferencia", "maximo"] == 0
    assert r.loc["Compra con tarjeta", "tasa_min"] == pytest.approx(0.0105, abs=1e-3)
    assert r.loc["Compra con tarjeta", "tasa_max"] == pytest.approx(0.0105, abs=1e-3)
    assert r.loc["Pago de servicios", "minimo"] == r.loc["Pago de servicios", "maximo"] == 0.80


def test_pago_de_servicios_solo_desde_el_lanzamiento(con):
    primera = con.execute(
        "SELECT MIN(fecha_hora)::DATE FROM transacciones WHERE tipo = 'Pago de servicios'").fetchone()[0]
    assert primera >= LANZAMIENTO_SERVICIOS


def test_campania_de_bono_dispara_activaciones_de_tiktok(con):
    r = con.execute("""
        SELECT date_trunc('month', fecha_activacion)::DATE AS mes, COUNT(*) AS n
        FROM clientes WHERE canal = 'TikTok Ads' AND fecha_activacion IS NOT NULL GROUP BY 1
    """).df().set_index("mes").n
    assert r[pd.Timestamp(2025, 11, 1)] > 1.8 * r[pd.Timestamp(2025, 10, 1)]


def test_organico_no_tiene_gasto(con):
    canales = {r[0] for r in con.execute("SELECT DISTINCT canal FROM gasto_marketing").fetchall()}
    assert "Orgánico" not in canales and len(canales) == 6
