import shutil
import subprocess
import sys
import types

import pytest

from conftest import CARPETA_MODELO, RAIZ
from semantico import despliegue as D
from semantico.errores import ERRORES, aplicar
from semantico.tmdl import cargar_modelo


@pytest.fixture(scope="module")
def ambientes():
    return D.cargar_ambientes(RAIZ / "ambientes.yaml")


def test_construir_reemplaza_parametros(tmp_path, ambientes):
    for amb in ("dev", "test", "prod"):
        destino = D.construir(CARPETA_MODELO, amb, ambientes, tmp_path)
        assert cargar_modelo(destino).parametros["RutaDatos"] == ambientes[amb]["parametros"]["RutaDatos"]
    prod = (tmp_path / "prod" / CARPETA_MODELO.name / "definition" / "expressions.tmdl").read_text()
    assert "matricula-dev" not in prod
    # el original no se toca
    assert cargar_modelo(CARPETA_MODELO).parametros["RutaDatos"].endswith("matricula-dev")


def test_ambiente_desconocido(tmp_path, ambientes):
    with pytest.raises(ValueError, match="Ambiente desconocido"):
        D.construir(CARPETA_MODELO, "qa", ambientes, tmp_path)


def _error(id_):
    return next(e for e in ERRORES if e.id == id_)


def test_plan_lista_cambios_e_impacto(tmp_path, modelo, carpeta_datos):
    nuevo = cargar_modelo(aplicar(CARPETA_MODELO, _error("E07"), tmp_path))
    p = D.plan(modelo, nuevo, carpeta_datos, {"Periodo[periodo]": "2026-2"})
    assert [(c.tipo, c.accion, c.objeto) for c in p.cambios] == [("medida", "modificada", "Ingresantes")]
    afectadas = {i.medida for i in p.impactos}
    # la medida tocada y las que dependen de ella
    assert {"Ingresantes", "Ingresantes año anterior", "Var. ingresantes vs año anterior"} <= afectadas
    assert "Alumnos matriculados" not in afectadas
    md = D.plan_markdown(p)
    assert "| medida | modificada | Ingresantes |" in md and "Valores que cambian" in md


def test_plan_de_relacion_y_formato(tmp_path, modelo):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    rel = cargar_modelo(aplicar(CARPETA_MODELO, _error("E15"), tmp_path / "a"))
    fmt = cargar_modelo(aplicar(CARPETA_MODELO, _error("E19"), tmp_path / "b"))
    assert D.comparar_modelos(modelo, rel)[0].tipo == "relacion"
    c = D.comparar_modelos(modelo, fmt)[0]
    assert c.objeto == "% pagó primera cuota" and "formato" in c.detalle
    assert D.plan_markdown(D.plan(modelo, modelo)).endswith("ni parámetros.\n")


def test_modelo_en_git(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(CARPETA_MODELO, repo / "modelo" / CARPETA_MODELO.name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-qm", "base"], check=True)
    carpeta = repo / "modelo" / CARPETA_MODELO.name
    archivo = carpeta / "definition" / "tables" / "Seccion.tmdl"
    archivo.write_text(archivo.read_text().replace("< 0.4", "< 0.35"))
    base = D.modelo_en_git("HEAD", carpeta, repo)
    cambios = D.comparar_modelos(base, cargar_modelo(carpeta))
    assert [c.objeto for c in cambios] == ["Secciones bajo 40%"]


def test_publicar_llama_a_fabric_cicd(tmp_path, ambientes, monkeypatch):
    llamadas = {}

    class Workspace:
        def __init__(self, **kw):
            llamadas["ws"] = kw

    fabric = types.ModuleType("fabric_cicd")
    fabric.FabricWorkspace = Workspace
    fabric.publish_all_items = lambda ws: llamadas.setdefault("publicado", ws)
    identidad = types.ModuleType("azure.identity")
    identidad.ClientSecretCredential = lambda *a: ("cred", a)
    monkeypatch.setitem(sys.modules, "fabric_cicd", fabric)
    monkeypatch.setitem(sys.modules, "azure.identity", identidad)

    destino = D.construir(CARPETA_MODELO, "test", ambientes, tmp_path)
    for v in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "FABRIC_WORKSPACE_TEST"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(RuntimeError, match="Faltan variables"):
        D.publicar(destino, "test", ambientes)

    for v in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.setenv(v, v.lower())
    monkeypatch.setenv("FABRIC_WORKSPACE_TEST", "ws-123")
    r = D.publicar(destino, "test", ambientes)
    ws = llamadas["ws"]
    assert ws["workspace_id"] == "ws-123" and ws["environment"] == "TEST"
    assert ws["item_type_in_scope"] == ["SemanticModel"]
    assert ws["repository_directory"] == str(tmp_path / "test")
    assert ws["token_credential"] == ("cred", ("azure_tenant_id", "azure_client_id", "azure_client_secret"))
    assert "publicado" in llamadas and r["workspace"] == "Mirasol BI - Pruebas"
