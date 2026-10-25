import hashlib
import json

import pandas as pd

from generar_datos import generar


def _huellas(carpeta):
    return {f.name: hashlib.md5(f.read_bytes()).hexdigest() for f in sorted(carpeta.iterdir())}


def test_misma_seed_mismos_archivos(tmp_path):
    a = generar(tmp_path / "a", escala=0.02, seed=3)
    b = generar(tmp_path / "b", escala=0.02, seed=3)
    assert _huellas(a) == _huellas(b)


def test_otra_seed_otros_datos(tmp_path):
    a = generar(tmp_path / "a", escala=0.02, seed=3)
    b = generar(tmp_path / "b", escala=0.02, seed=4)
    assert _huellas(a)["eventos_matricula.csv"] != _huellas(b)["eventos_matricula.csv"]


def test_export_trae_los_problemas_tipicos(raw):
    ev = pd.read_csv(raw / "eventos_matricula.csv", dtype=str)
    assert ev["codigo_alumno"].str.contains(r"^\s|\s$|^u", regex=True).any()
    assert ev["seccion_id"].str.startswith("PRB-").any()
    assert ev["fecha_hora"].str.match(r"\d{2}/\d{2}/\d{4}").any()
    assert pd.read_csv(raw / "pagos.csv", dtype=str)["monto"].str.startswith("S/").any()
    assert (pd.read_csv(raw / "notas.csv", dtype=str)["nota_final"] == "NSP").any()


def test_manifiesto_registra_cada_anomalia(raw):
    meta = json.loads((raw / "_anomalias.json").read_text(encoding="utf-8"))
    assert meta["periodos"][0] == "2024-1" and meta["periodos"][-1] == "2026-2"
    assert all(v > 0 for v in meta["anomalias"].values())


def test_periodo_en_curso_no_tiene_notas(raw):
    notas = pd.read_csv(raw / "notas.csv", dtype=str)
    assert not notas["seccion_id"].str.startswith("2026-2").any()
