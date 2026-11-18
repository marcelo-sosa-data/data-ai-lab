import json
from datetime import date

import pandas as pd

from comprobantes import evaluacion as ev
from comprobantes.esquema import Comprobante
from comprobantes.llm import ExtractorGuionado
from comprobantes.procesar import leer_lote, rutear
from comprobantes.reglas import Observacion
from comprobantes.ruteo import decidir


def _desde_verdad(fila) -> Comprobante:
    return Comprobante(
        tipo=fila["tipo"], ruc_emisor=fila["ruc_emisor"],
        ruc_receptor=None if pd.isna(fila["ruc_receptor"]) else fila["ruc_receptor"],
        serie=fila["serie"], numero=int(fila["numero"]), fecha_emision=fila["fecha_emision"].date(),
        moneda=fila["moneda"], base_imponible=fila["base_imponible"], igv=fila["igv"], total=fila["total"],
        orden_compra=None if pd.isna(fila["orden_compra"]) else fila["orden_compra"])


def test_decidir():
    c = Comprobante(tipo="factura", ruc_emisor="20111222333", serie="F001", numero=1, total=1.0)
    assert decidir(c, {}, [], 0.5).destino == "aprobado"
    assert decidir(c, {}, [Observacion("sin_credito_fiscal", "", "aviso")], 0.5).destino == "aprobado"
    d = decidir(c, {"tipo": 1.0, "ruc_emisor": 0.9, "serie": 0.3, "numero": 0.3, "total": 0.9}, [],
                {"serie": 0.5, "numero": 0.2})
    assert d.destino == "revision" and d.campos_dudosos == ["serie"]
    assert decidir(c, {}, [Observacion("excede_oc", "", "negocio")], 0.5).motivos == ["excede_oc"]


def test_lectura_perfecta_solo_deja_en_revision_los_errores_del_proveedor(tablas, ctx, ruta_db):
    v, rec = tablas["aux_verdad"], tablas["recepcion"]
    extractor = ExtractorGuionado({r["archivo"]: _desde_verdad(r) for r in v.to_dict("records")})
    lecturas = leer_lote(rec, ruta_db.parent / "imagenes", extractor)
    dec = rutear(lecturas, rec, ctx, 0.5, v)

    # lo sano se aprueba entero; los errores sembrados van todos a revisión con su motivo
    con_anomalia = dec.merge(v[["doc_id", "anomalia"]], on="doc_id")
    sanos = con_anomalia[con_anomalia["anomalia"].isna()]
    assert (sanos["destino"] == "aprobado").mean() > 0.97
    det = ev.deteccion_por_anomalia(dec, v)
    assert (det["con_motivo"] == det["n"]).all()

    ac = ev.aciertos(lecturas, v)
    assert ac["doc_correcto"].all()
    m = ev.metricas_ruteo(dec, ac, v)
    assert m["aprobados_con_error"] == 0 and m["aprobados_con_anomalia"] == 0

    p = ev.as_is_vs_to_be(dec, v, ac)
    assert p["to_be"]["detectadas_en_recepcion"] == p["con_anomalia"]
    assert p["to_be"]["pagadas_sin_detectar"] == 0
    assert p["as_is"]["pagadas_sin_detectar"] > 0


def test_un_error_de_lectura_que_rompe_la_aritmetica_va_a_revision(tablas, ctx, ruta_db):
    v, rec = tablas["aux_verdad"], tablas["recepcion"]
    sano = v[v["anomalia"].isna() & (v["tipo"] == "factura")].iloc[0]
    lecturas = {r["archivo"]: _desde_verdad(r) for r in v.to_dict("records")}
    mal = lecturas[sano["archivo"]].model_copy(update={"total": sano["total"] + 9.0})
    lecturas[sano["archivo"]] = mal
    lec = leer_lote(rec, ruta_db.parent / "imagenes", ExtractorGuionado(lecturas, confianza=None))
    dec = rutear(lec, rec, ctx, 0.5, v, usar_confianza=False).set_index("doc_id")
    assert dec.loc[sano["doc_id"], "destino"] == "revision"
    assert "total_no_cuadra" in json.loads(dec.loc[sano["doc_id"], "motivos"])
    # corregida la lectura, los controles vuelven a correr y ya no observan nada
    assert json.loads(dec.loc[sano["doc_id"], "motivos_tras_correccion"]) == []


def test_umbral_por_percentil_y_eleccion():
    lecturas = pd.DataFrame({"doc_id": [1, 2, 3, 4],
                             "confianza": [json.dumps({"total": c}) for c in (0.9, 0.8, 0.7, 0.2)]})
    ac = pd.DataFrame({"doc_id": [1, 2, 3, 4], **{k: True for k in ev.CAMPOS}})
    ac.loc[3, "total"] = False
    u = ev.umbrales_por_campo(lecturas, ac, 0.5)
    assert u["total"] == 0.8
    curva = pd.DataFrame({"percentil": [0.0, 0.1, 0.2], "tasa_error_aprobados": [0.05, 0.008, 0.0],
                          "umbrales": [json.dumps({"total": x}) for x in (0.0, 0.5, 0.7)]})
    assert ev.elegir_umbral(curva, meta=0.01) == (0.1, {"total": 0.5})
