import copy

import pytest
import yaml

from kpis.modelo import Definicion, ErrorSemantico, cargar
from kpis.rutas import ruta_semantica

CRUDO = yaml.safe_load(ruta_semantica().read_text(encoding="utf-8"))


def _con(cambio) -> dict:
    d = copy.deepcopy(CRUDO)
    cambio(d)
    return d


def test_el_yaml_del_proyecto_es_valido():
    d = cargar(ruta_semantica())
    assert d.hechos == "transacciones"
    assert "rubro" in d.dimensiones() and "hora" in d.dimensiones()
    assert d.medidas_de("tpv_por_comercio") == ["tpv", "comercios_activos"]
    assert not d.medidas["comercios_activos"].aditiva and d.medidas["tpv"].aditiva


def test_medida_inexistente():
    d = _con(lambda d: d["metricas"]["tasa_aprobacion"].update(numerador="aprobados"))
    with pytest.raises(ValueError, match="aprobados no existe"):
        Definicion.model_validate(d)


def test_ciclo_en_derivadas():
    def ciclo(d):
        d["metricas"]["a"] = {"tipo": "derivada", "expr": "b * 2", "etiqueta": "a"}
        d["metricas"]["b"] = {"tipo": "derivada", "expr": "a / 2", "etiqueta": "b"}
    with pytest.raises(ValueError, match="ciclo"):
        Definicion.model_validate(_con(ciclo))


def test_ratio_sin_denominador():
    d = _con(lambda d: d["metricas"]["take_rate"].pop("denominador"))
    with pytest.raises(ValueError, match="denominador"):
        Definicion.model_validate(d)


def test_suma_sin_expr():
    d = _con(lambda d: d["medidas"]["tpv"].pop("expr"))
    with pytest.raises(ValueError, match="necesita expr"):
        Definicion.model_validate(d)


def test_dimension_repetida_en_dos_modelos():
    d = _con(lambda d: d["modelos"]["comercios"]["dimensiones"].update(metodo={"expr": "rubro"}))
    with pytest.raises(ValueError, match="metodo"):
        Definicion.model_validate(d)


def test_modelo_sin_entidad_comun_no_se_puede_unir():
    d = _con(lambda d: d["modelos"]["comercios"]["entidades"].update(
        comercio={"columna": "id_comercio", "tipo": "foranea"}))
    with pytest.raises(ValueError, match="no comparte una entidad"):
        Definicion.model_validate(d)


def test_campo_desconocido_se_rechaza():
    d = _con(lambda d: d["metricas"]["tpv"].update(formatto="soles"))
    with pytest.raises(ValueError):
        Definicion.model_validate(d)
