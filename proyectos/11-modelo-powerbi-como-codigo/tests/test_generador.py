import pandas as pd


def _leer(carpeta, nombre):
    return pd.read_parquet(carpeta / f"{nombre}.parquet")


def test_archivos_y_claves(carpeta_datos):
    for t in ("periodo", "sede", "carrera", "curso", "alumno", "matricula", "seccion", "inscripcion"):
        assert (carpeta_datos / f"{t}.parquet").exists()
    m = _leer(carpeta_datos, "matricula")
    assert not m.duplicated(["id_alumno", "id_periodo"]).any()
    assert _leer(carpeta_datos, "seccion")["id_seccion"].is_unique
    assert _leer(carpeta_datos, "inscripcion")["id_inscripcion"].is_unique


def test_retiro_total_deja_cero_creditos(carpeta_datos):
    m = _leer(carpeta_datos, "matricula")
    assert (m.loc[m["retiro_total"], "creditos_vigentes"] == 0).all()
    assert (m.loc[~m["retiro_total"], "creditos_vigentes"] > 0).all()


def test_inscripciones_consistentes_con_matricula(carpeta_datos):
    m = _leer(carpeta_datos, "matricula")
    i = _leer(carpeta_datos, "inscripcion").merge(_leer(carpeta_datos, "seccion"), on="id_seccion")
    vig = i[i["estado"] == "Vigente"].groupby(["id_alumno", "id_periodo"])["creditos"].sum()
    cruce = m.set_index(["id_alumno", "id_periodo"])["creditos_vigentes"]
    assert (vig.reindex(cruce.index).fillna(0) == cruce).all()


def test_ingresan_menos_en_2026_2(carpeta_datos):
    m = _leer(carpeta_datos, "matricula").merge(_leer(carpeta_datos, "periodo"), on="id_periodo")
    ing = m[m["tipo_alumno"] == "Ingresante"].groupby("periodo").size()
    assert ing["2026-2"] < ing["2025-2"]
    assert ing["2026-1"] > ing["2026-2"]  # el primer semestre ingresa más


def test_misma_semilla_mismos_datos(tmp_path):
    from generar_datos import generar
    a = generar(tmp_path / "a", escala=0.03, seed=5)
    b = generar(tmp_path / "b", escala=0.03, seed=5)
    pd.testing.assert_frame_equal(_leer(a, "inscripcion"), _leer(b, "inscripcion"))
