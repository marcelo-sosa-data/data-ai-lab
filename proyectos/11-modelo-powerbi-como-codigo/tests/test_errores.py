import pytest

from conftest import CARPETA_MODELO
from semantico.errores import ERRORES, aplicar, evaluar_todos


def test_cada_error_encuentra_su_texto(tmp_path):
    for e in ERRORES:
        destino = tmp_path / e.id
        destino.mkdir()
        aplicar(CARPETA_MODELO, e, destino)


def test_los_controles_atrapan_lo_que_deben(carpeta_datos, casos, con):
    res = {r.error.id: r for r in evaluar_todos(CARPETA_MODELO, carpeta_datos, casos, con)}
    # solo el cambio de formato pasa: es un aviso y no bloquea el merge
    assert [i for i, r in res.items() if not r.atrapado] == ["E19"]
    assert res["E19"].avisos == ["R03"]
    # los que no cambian ningún número solo los atrapan las reglas
    for i, regla in {"E12": "R04", "E15": "R07", "E17": "R09"}.items():
        assert res[i].reglas == [regla] and not res[i].pruebas_fallidas
    # COUNTROWS da lo mismo que DISTINCTCOUNT por periodo; solo lo delata el caso sin filtro
    assert res["E02"].pruebas_fallidas == ["matriculados_historico_sin_filtro"]


def test_error_mal_escrito_falla(tmp_path):
    from semantico.errores import Error
    with pytest.raises(ValueError, match="no encuentro"):
        aplicar(CARPETA_MODELO, Error("X", "x", "tables/Matricula.tmdl", "texto que no está", "y"), tmp_path)
