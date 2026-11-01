import copy

import duckdb
import pytest
import yaml

from kpis.capa import CapaSemantica
from kpis.modelo import Definicion
from kpis.rutas import ruta_semantica
from kpis.validacion import conciliacion, huerfanos, no_aditividad, validar


def test_la_capa_valida_contra_la_base(capa, con):
    chequeos, conc = validar(capa, con)
    assert all(c.ok for c in chequeos), [c for c in chequeos if not c.ok]
    assert conc.ok.all()


def test_conciliacion_detecta_filas_duplicadas_en_una_dimension(capa, ruta_db):
    # el maestro trae comercios duplicados: el join a comercios multiplica cobros
    con = duckdb.connect()
    con.execute(f"ATTACH '{ruta_db}' AS src (READ_ONLY)")
    con.execute("CREATE TABLE transacciones AS SELECT * FROM src.transacciones")
    con.execute("""CREATE TABLE comercios AS SELECT * FROM src.comercios
                   UNION ALL SELECT * FROM src.comercios WHERE rubro = 'ropa'""")
    conc = conciliacion(capa, con)
    malas = set(conc[~conc.ok].dimension)
    assert {"rubro", "region", "segmento"} <= malas
    assert "emisor" not in malas  # no pasa por el join


def test_columna_que_no_existe_falla_en_esquema(con):
    crudo = yaml.safe_load(ruta_semantica().read_text(encoding="utf-8"))
    d = copy.deepcopy(crudo)
    d["modelos"]["comercios"]["dimensiones"]["distrito"] = {"expr": "distrito"}
    capa = CapaSemantica(Definicion.model_validate(d))
    chequeos, _ = validar(capa, con)
    malo = [c for c in chequeos if not c.ok]
    assert len(malo) == 1 and "distrito" in malo[0].detalle


def test_huerfanos_y_no_aditividad(capa, con):
    h = huerfanos(con)
    assert h["transacciones"] > 0 and h["comercios"] >= 1
    na = no_aditividad(capa, con, "2026-08-01")["comercios_activos"]
    assert na["suma_diaria"] > 5 * na["mes"]  # un comercio activo cuenta una vez al mes, no 31
    assert na["mes"] >= na["promedio_diario"]
