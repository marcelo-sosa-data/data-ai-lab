from datetime import date

from reglamento.corpus import limpiar


def test_limpiar_quita_pie_y_une_guiones():
    crudo = ("Los estud-\niantes del tercio superior\n"
             "Universidad Qhapaq Ñan — Secretaría General | Pág. 3\nsiguen aquí")
    limpio = limpiar(crudo)
    assert "estudiantes" in limpio
    assert "Pág." not in limpio and "siguen aquí" in limpio


def test_no_queda_ruido_de_pdf(fragmentos):
    for f in fragmentos:
        assert "Pág." not in f.texto and "-  " not in f.texto
        assert "\n" not in f.texto


def test_cada_articulo_es_un_fragmento(por_id):
    assert por_id["RE-2024/art-1"].capitulo.startswith("CAPÍTULO I")
    assert por_id["RP-2025/art-5"].titulo == "Mora"
    assert "RCU-014-2026/art-1" not in por_id      # la resolución no entra como texto propio


def test_resolucion_modifica_y_deroga(por_id):
    viejo, nuevo = por_id["RE-2024/art-10"], por_id["RE-2024/art-10@2026-03-01"]
    assert "semana 10" in viejo.texto and "semana 8" in nuevo.texto
    assert viejo.vigente_hasta == date(2026, 2, 28)
    assert nuevo.vigente_desde == date(2026, 3, 1) and nuevo.vigente_hasta is None
    assert nuevo.fuente == "RCU-014-2026" and nuevo.capitulo == viejo.capitulo
    assert nuevo.cita == "RE-2024, art. 10 (mod. RCU-014-2026)"


def test_articulo_incorporado_hereda_capitulo(por_id):
    ia = por_id["RE-2024/art-35-A@2026-03-01"]
    assert ia.capitulo == por_id["RE-2024/art-35"].capitulo
    assert not ia.vigente(date(2025, 10, 1)) and ia.vigente(date(2026, 9, 1))


def test_vigencia_por_fecha(por_id):
    viejo = por_id["RE-2024/art-17"]
    assert viejo.vigente(date(2026, 2, 28)) and not viejo.vigente(date(2026, 3, 1))
    assert not viejo.vigente(date(2024, 2, 29))    # antes de que rija el reglamento
