from datetime import date

import pyarrow.compute as pc
from pyiceberg.expressions import EqualTo

from conftest import escribir_lote, evento, fila
from lakehouse import catalogo
from lakehouse.ingesta import _marcar, _aplicar_estado, cargar_bronce, lotes_pendientes, procesar_lote, ResultadoLote

import duckdb

REG = fila()
REC = fila(estado="recogido", actualizado_en="2026-08-03 10:30:00")
RUTA = fila(estado="en_ruta", id_courier=120, actualizado_en="2026-08-03 11:00:00")
ENT = fila(estado="entregado", intentos=1, entregado_en="2026-08-03 14:00:00", actualizado_en="2026-08-03 14:02:00")


def _procesar(v, *lotes):
    return [procesar_lote(v["tablas"], v["contrato"], x, v["dir_cdc"]) for x in lotes]


def _plata(v):
    return v["tablas"]["plata"].scan().to_pandas()


def _estados(v):
    return v["tablas"]["estados"].scan().to_pandas().sort_values("lsn")


def test_evento_tardio_no_hace_retroceder_el_estado(vacio):
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", REG), evento(30, "u", RUTA, REC)])
    escribir_lote(vacio["dir_cdc"], "2026-08-03T18", [evento(20, "u", REC, REG)])  # recogido llega tarde
    _, r = _procesar(vacio, "2026-08-03T12", "2026-08-03T18")
    p = _plata(vacio)
    assert list(p["estado"]) == ["en_ruta"] and list(p["_lsn"]) == [30]
    assert r.tardios == 1 and r.descartados_lsn == 1
    # pero el historial sí lo registra: es un cambio de estado real, solo llegó tarde
    assert list(_estados(vacio)["estado"]) == ["registrado", "recogido", "en_ruta"]


def test_duplicado_no_se_cuenta_dos_veces(vacio):
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", REG), evento(20, "u", REC, REG)])
    escribir_lote(vacio["dir_cdc"], "2026-08-03T18", [evento(20, "u", REC, REG), evento(20, "u", REC, REG),
                                                       evento(40, "u", ENT, REC)])
    _, r = _procesar(vacio, "2026-08-03T12", "2026-08-03T18")
    assert r.eventos == 3 and r.duplicados == 2
    assert list(_estados(vacio)["estado"]) == ["registrado", "recogido", "entregado"]
    assert list(_plata(vacio)["estado"]) == ["entregado"]


def test_borrado_saca_el_envio_de_plata(vacio):
    otro = fila(id_envio=2, codigo_seguimiento="KL2607000002")
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", REG), evento(11, "c", otro)])
    escribir_lote(vacio["dir_cdc"], "2026-08-10T06", [evento(50, "d", None, REG, ts="2026-08-10 03:00:00")])
    _, r = _procesar(vacio, "2026-08-03T12", "2026-08-10T06")
    assert r.borrados == 1 and list(_plata(vacio)["id_envio"]) == [2]


def test_reprocesar_un_lote_no_cambia_nada(vacio):
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", REG), evento(20, "u", REC, REG)])
    _procesar(vacio, "2026-08-03T12")
    snaps = {k: len(t.snapshots()) for k, t in vacio["tablas"].items()}
    (r,) = _procesar(vacio, "2026-08-03T12")
    assert r.eventos == 0
    assert snaps == {k: len(t.snapshots()) for k, t in vacio["tablas"].items()}
    assert len(_plata(vacio)) == 1 and len(_estados(vacio)) == 2


def test_retoma_si_se_cae_entre_plata_y_el_historial(vacio):
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", REG), evento(20, "u", REC, REG)])
    t, c = vacio["tablas"], vacio["contrato"].vigente(date(2026, 8, 3))
    cargar_bronce(t["bronce"], "2026-08-03T12", vacio["dir_cdc"])
    con = duckdb.connect()
    _marcar(con, t["bronce"], c, "2026-08-03T12")
    _aplicar_estado(t["plata"], c, con, "2026-08-03T12", ResultadoLote("2026-08-03T12"))
    # se cayó aquí: plata y bronce tienen el lote; historial y cuarentena no
    assert lotes_pendientes(t, vacio["dir_cdc"]) == ["2026-08-03T12"]
    snaps_plata = len(t["plata"].snapshots())
    _procesar(vacio, "2026-08-03T12")
    assert len(t["plata"].snapshots()) == snaps_plata
    assert len(_estados(vacio)) == 2 and len(t["bronce"].scan().to_arrow()) == 2
    assert lotes_pendientes(t, vacio["dir_cdc"]) == []


def test_cuarentena_y_correccion_en_origen(vacio):
    malo = fila(peso_kg=1500.0)
    bueno = fila(peso_kg=1.5, actualizado_en="2026-08-04 11:00:00")
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", malo)])
    escribir_lote(vacio["dir_cdc"], "2026-08-04T12", [evento(90, "u", bueno, malo)])
    r1, r2 = _procesar(vacio, "2026-08-03T12", "2026-08-04T12")
    assert r1.cuarentena == 1 and r1.insertados == 0 and r2.insertados == 1
    q = vacio["tablas"]["cuarentena"].scan().to_pandas()
    assert list(q["violaciones"].iloc[0]) == ["peso_kg.maximo"] and bool(q["en_historial"].iloc[0])
    assert list(_plata(vacio)["peso_kg"]) == [1.5]
    assert list(_estados(vacio)["estado"]) == ["registrado"]  # el peso malo no borra el registro del estado


def test_columna_nueva_espera_al_contrato_y_se_rellena_desde_bronce(vacio):
    con_franja = fila(id_envio=7, codigo_seguimiento="KL2607000007", registrado_en="2026-09-15 10:00:00",
                      fecha_promesa="2026-09-16", actualizado_en="2026-09-15 10:00:00", franja_horaria="tarde")
    entregado = {**con_franja, "estado": "entregado", "intentos": 1, "entregado_en": "2026-09-16 15:00:00",
                 "actualizado_en": "2026-09-16 15:01:00"}
    escribir_lote(vacio["dir_cdc"], "2026-09-15T12", [evento(10, "c", con_franja)])
    escribir_lote(vacio["dir_cdc"], "2026-09-16T18", [evento(20, "u", entregado, con_franja)])
    escribir_lote(vacio["dir_cdc"], "2026-09-17T12", [evento(30, "c", fila(registrado_en="2026-09-17 09:00:00",
                                                                        fecha_promesa="2026-09-18",
                                                                        actualizado_en="2026-09-17 09:00:00",
                                                                        franja_horaria="manana"))])
    r1, r2 = _procesar(vacio, "2026-09-15T12", "2026-09-16T18")
    # 15 y 16: rige la 1.0.0, la columna se avisa y queda solo en bronce
    assert r1.no_declaradas == ["franja_horaria"] and r1.version_contrato == "1.0.0"
    assert "franja_horaria" not in vacio["tablas"]["plata"].schema().column_names
    (r3,) = _procesar(vacio, "2026-09-17T12")
    # 17: rige la 1.1.0, plata agrega la columna y rellena el envío 7 con el evento de bronce
    assert r3.version_contrato == "1.1.0" and r3.columnas_nuevas == ["franja_horaria"] and r3.rellenados == 1
    p = _plata(vacio).set_index("id_envio")
    assert p.loc[7, "franja_horaria"] == "tarde" and p.loc[1, "franja_horaria"] == "manana"
    assert len(vacio["tablas"]["plata"].schemas()) == 2


def test_marca_de_agua_en_la_tabla(vacio):
    escribir_lote(vacio["dir_cdc"], "2026-08-03T12", [evento(10, "c", REG)])
    _procesar(vacio, "2026-08-03T12")
    for t in ("bronce", "plata", "estados", "cuarentena"):
        assert catalogo.ultimo_lote(vacio["tablas"][t]) == "2026-08-03T12"
    snap = vacio["tablas"]["plata"].current_snapshot()
    assert snap.summary["lote"] == "2026-08-03T12"
    assert pc.sum(vacio["tablas"]["bronce"].scan(row_filter=EqualTo("lsn", 10)).to_arrow()["lsn"]).as_py() == 10
