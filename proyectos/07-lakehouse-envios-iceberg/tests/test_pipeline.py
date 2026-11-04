from datetime import date

import pandas as pd

from lakehouse.auditoria import conciliar, ingenuo
from lakehouse.calendario import corte_de
from lakehouse.mantenimiento import estadisticas, mantener
from lakehouse.oro import cortes
from lakehouse.viaje import promesa_por_corte, reportado_vs_final, todos_los_cortes


def test_plata_concilia_con_origen(simulado, contrato):
    t = simulado["tablas"]
    c = conciliar(t["plata"], t["cuarentena"], contrato, simulado["dir"] / "origen" / "envios.parquet")
    assert c["sobran_en_plata"] == 0
    assert c["columnas_distintas"] == {}
    assert c["faltan_en_plata"] == c["faltan_explicados_por_cuarentena"]


def test_aplicar_en_orden_de_llegada_se_equivoca(simulado, contrato):
    t = simulado["tablas"]
    m = ingenuo(t["bronce"], t["plata"], contrato, simulado["dir"] / "origen" / "envios.parquet")
    assert m["estado_distinto"] > 0
    assert m["plata_estado_distinto"] == 0


def test_cuarentena_atrapa_el_peso_en_gramos(simulado):
    q = simulado["tablas"]["cuarentena"].scan().to_pandas().explode("violaciones")
    gramos = q[q["violaciones"] == "peso_kg.maximo"]
    assert set(gramos["id_envio"]) <= set(simulado["manifiesto"]["peso_en_gramos"])
    assert len(gramos) > 0 and gramos["lote"].min() >= "2026-08-18T12"
    lotes = pd.DataFrame(simulado["filas"])
    alto = lotes[lotes["cuarentena"] / (lotes["eventos"] - lotes["duplicados"]).clip(lower=1) > 0.02]
    assert {corte_de(x).date() for x in alto["lote"]} <= {date(2026, 8, d) for d in range(18, 22)}


def test_un_corte_de_oro_por_manana(simulado):
    dias = cortes(simulado["tablas"]["oro"])
    assert set(dias) == {date(2026, 8, d) for d in range(15, 25)}


def test_viaje_en_el_tiempo(simulado):
    oro = simulado["tablas"]["oro"]
    serie = promesa_por_corte(oro, date(2026, 8, 18))
    assert serie["corte"].min() == date(2026, 8, 19)
    # los entregados a tiempo solo pueden subir: las entregas tardías en sincronizar se suman después
    assert serie["a_tiempo"].is_monotonic_increasing
    comp = reportado_vs_final(todos_los_cortes(oro))
    assert comp["brecha_pp"].mean() > 0  # en promedio el OTD de la mañana siguiente sale bajo


def test_mantenimiento_no_cambia_los_datos(simulado):
    t = simulado["tablas"]["estados"]
    antes = t.scan().to_pandas().sort_values("lsn").reset_index(drop=True)
    e0 = estadisticas(t)
    r = mantener(t, minimo_archivos=2, conservar=1)
    e1 = estadisticas(t)
    despues = t.scan().to_pandas().sort_values("lsn").reset_index(drop=True)
    pd.testing.assert_frame_equal(antes, despues)
    assert e1.archivos_datos < e0.archivos_datos and e1.snapshots < e0.snapshots
    assert r["huerfanos_borrados"] > 0 and e1.archivos_en_disco < e0.archivos_en_disco
