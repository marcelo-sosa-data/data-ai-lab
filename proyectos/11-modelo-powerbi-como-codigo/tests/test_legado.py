from conftest import RAIZ
from semantico.legado import cargar_legado, comparar, revisar_legado


def test_tres_definiciones_de_matriculados(motor):
    legado = cargar_legado(RAIZ / "legado")
    assert set(legado) == {"Registros Académicos", "Finanzas", "Dirección Académica"}
    filas = {(f.indicador, f.reporte): f.valor for f in comparar(motor, legado, {"Periodo[periodo]": "2026-2"})}
    oficial = filas[("Alumnos matriculados", "Modelo único")]
    # Registros cuenta también a quien se retiró de todo; Finanzas solo a quien pagó;
    # Dirección solo a regulares
    assert filas[("Alumnos matriculados", "Registros Académicos")] > oficial
    assert filas[("Alumnos matriculados", "Finanzas")] < oficial
    assert filas[("Alumnos matriculados", "Dirección Académica")] < oficial
    # Dirección calcula bien la ocupación; Registros cuenta las inscripciones retiradas
    assert filas[("Ocupación de secciones", "Dirección Académica")] == filas[("Ocupación de secciones", "Modelo único")]
    assert filas[("Ocupación de secciones", "Registros Académicos")] > filas[("Ocupación de secciones", "Modelo único")]


def test_reglas_sobre_el_legado(modelo):
    hallazgos = revisar_legado(modelo, cargar_legado(RAIZ / "legado"))
    finanzas = {h.regla for h in hallazgos["Finanzas"]}
    assert {"R01", "R04", "R14"} <= finanzas
    assert all(h.objeto.startswith("[") and " / " not in h.objeto for hs in hallazgos.values() for h in hs)
