import pandas as pd
import pytest

from tramites import catalogos as K
from tramites.lectura import leer


def test_quita_duplicados_y_normaliza_actividades(log):
    assert log.hallazgos["duplicados"] > 0
    assert not log.eventos.duplicated(["id_tramite", "actividad", "inicio", "fin"]).any()
    assert log.hallazgos["actividades_desconocidas"] == []
    assert K.EVALUAR in set(log.eventos["actividad"])


def test_codigo_de_alumno_queda_como_texto(log):
    assert log.tramites["codigo_alumno"].str.match(r"^U\d{7}$").all()
    assert log.tramites["nombre_alumno"].str.count(" ").ge(2).all()


def test_estados_de_cierre(log):
    estados = set(log.tramites["estado"])
    assert {"Atendido", "Archivado"} <= estados
    cerrados = log.tramites[log.tramites["estado"] != "Abierto"]
    assert cerrados["fin"].notna().all()


def test_encabezados_cambiados_y_fechas_iso(carpeta, tmp_path):
    """Si el export cambia nombres de columnas, orden, tildes y formato de fecha, se lee igual."""
    crudo = pd.read_csv(carpeta / "exports" / "log_tramites.csv", sep=";", dtype=str,
                        keep_default_na=False, encoding="utf-8-sig")
    otro = crudo.rename(columns={"NRO_TRAMITE": "Nro Trámite", "ACTIVIDAD": "Tarea",
                                 "F_FIN": "Fecha_Fin", "F_INICIO": "Fecha_Inicio"})
    otro = otro[["Tarea", "Nro Trámite", "AREA", "USUARIO", "Fecha_Inicio", "Fecha_Fin"]]
    otro["Tarea"] = otro["Tarea"].str.replace("Í", "I").str.replace("Ó", "O")
    otro["Fecha_Fin"] = pd.to_datetime(otro["Fecha_Fin"], format="%d/%m/%Y %H:%M:%S").dt.strftime("%Y-%m-%d %H:%M:%S")
    otro.to_csv(tmp_path / "log_tramites.csv", index=False, sep=",")
    (tmp_path / "tramites.csv").write_bytes((carpeta / "exports" / "tramites.csv").read_bytes())
    a, b = leer(carpeta / "exports"), leer(tmp_path)
    assert len(a.eventos) == len(b.eventos)
    assert b.hallazgos["actividades_desconocidas"] == []
    assert (a.eventos["fin"].values == b.eventos["fin"].values).all()


def test_falta_columna_obligatoria(carpeta, tmp_path):
    crudo = pd.read_csv(carpeta / "exports" / "log_tramites.csv", sep=";", dtype=str, encoding="utf-8-sig")
    crudo.drop(columns="ACTIVIDAD").to_csv(tmp_path / "log_tramites.csv", index=False, sep=";")
    (tmp_path / "tramites.csv").write_bytes((carpeta / "exports" / "tramites.csv").read_bytes())
    with pytest.raises(ValueError, match="actividad"):
        leer(tmp_path)
