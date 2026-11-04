from datetime import date

import pytest

dagster = pytest.importorskip("dagster")

from dagster import build_sensor_context, materialize  # noqa: E402

from generar_datos import generar  # noqa: E402
from lakehouse import catalogo  # noqa: E402
from lakehouse.definiciones import Lakehouse, cdc_bronce, defs, entregas_diarias, lotes_nuevos, plata  # noqa: E402


@pytest.fixture
def recurso(tmp_path):
    generar(tmp_path, escala=0.05, seed=5, desde=date(2026, 8, 17), hasta=date(2026, 8, 19))
    return Lakehouse(datos=str(tmp_path))


def _config(hasta):
    c = {"config": {"hasta": hasta}}
    return {"ops": {"bronce__cdc_envios": c, "plata": c, "oro__entregas_diarias": c}}


def test_definiciones_cargan():
    assert {j.name for j in defs.resolve_all_job_defs()} >= {"ingesta", "mantenimiento_semanal"}
    assert defs.resolve_sensor_def("lotes_nuevos")


def test_materializar_hasta_un_corte(recurso):
    r = materialize([cdc_bronce, plata, entregas_diarias], resources={"lakehouse": recurso},
                    run_config=_config("2026-08-18T06"))
    assert r.success
    checks = {c.check_name: c.passed for c in r.get_asset_check_evaluations()}
    assert checks["clave_unica"]
    t = catalogo.tablas(catalogo.abrir(recurso.datos + "/lakehouse"))
    assert catalogo.ultimo_lote(t["plata"]) == "2026-08-18T06"
    assert catalogo.ultimo_lote(t["oro"]) == "2026-08-18T06"
    # la regla del peso salta con el incidente de la app de agencias
    r = materialize([cdc_bronce, plata, entregas_diarias], resources={"lakehouse": recurso},
                    run_config=_config("2026-08-19T18"))
    checks = {c.check_name: c.passed for c in r.get_asset_check_evaluations()}
    assert r.success and checks["clave_unica"] and not checks["cuarentena_bajo_umbral"]


def test_sensor_un_run_por_lote(recurso):
    with build_sensor_context(resources={"lakehouse": recurso}) as ctx:
        pedidos = list(lotes_nuevos(ctx))
    assert pedidos and pedidos[0].run_key == "2026-08-17T06"
    assert len({p.run_key for p in pedidos}) == len(pedidos)
