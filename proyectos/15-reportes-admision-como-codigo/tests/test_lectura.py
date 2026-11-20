import pandas as pd

from admision import catalogos as K
from admision.lectura import leer_inscripciones


def test_lee_los_dos_formatos_del_sistema(lectura):
    assert lectura.hallazgos == []
    ins = lectura.inscripciones
    assert set(ins["campania"]) == set(K.CAMPANIAS)
    reales = ins[~ins["es_prueba"]]
    # 2026-1 viene en cp1252 con tildes y 2027-1 en mayúsculas sin tildes: los dos quedan con el nombre oficial
    assert set(reales["modalidad"]) <= set(K.MODALIDADES)
    assert set(reales["carrera"]) == set(K.CARRERAS)
    assert set(reales["estado"]) == set(K.ESTADOS.values())
    assert ins["fecha_inscripcion"].notna().all()


def test_documentos_quedan_como_texto_con_su_largo(lectura):
    ins = lectura.inscripciones
    dni = ins.loc[ins["tipo_documento"] == "DNI", "documento"]
    assert dni.str.fullmatch(r"\d{8}").all()
    assert dni.str.startswith("0").any()


def test_pagos_clasifican_concepto_y_referencia(lectura):
    p = lectura.pagos
    assert set(p["tipo_pago"]) == {"MATRICULA", "DERECHO", "OTRO"}
    mat = p[p["tipo_pago"] == "MATRICULA"]
    # la mayoría de matrículas trae el código, con o sin adornos
    assert 0.75 < mat["referencia_codigo"].notna().mean() < 0.95


def test_columna_faltante_es_error_y_no_rompe(tmp_path):
    ruta = tmp_path / "admision.csv"
    pd.DataFrame({"codigo_postulante": ["1"], "documento": ["12"]}).to_csv(ruta, index=False)
    hallazgos = []
    assert leer_inscripciones(ruta, "2027-1", hallazgos) is None
    assert hallazgos[0]["regla"] == "columna_faltante" and hallazgos[0]["severidad"] == "error"


def test_columna_nueva_es_solo_aviso(carpeta, tmp_path):
    origen = carpeta / "crudo" / "2027-1" / "admision_inscripciones_2027-1.csv"
    df = pd.read_csv(origen, dtype=str, keep_default_na=False)
    df.insert(3, "correo", "x@correo.pe")
    ruta = tmp_path / "admision.csv"
    df.to_csv(ruta, index=False)
    hallazgos = []
    leido = leer_inscripciones(ruta, "2027-1", hallazgos)
    assert leido is not None and len(leido) == len(df)
    assert [h["severidad"] for h in hallazgos] == ["aviso"]
