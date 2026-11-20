from admision.regla_actual import _valor, reporte


def test_valor_como_excel():
    assert _valor(" 02138554 ") == 2138554
    assert _valor(2138554) == 2138554
    assert _valor("4567 8912") is None
    assert _valor("AB123456") is None


def test_el_excel_infla_postulantes_y_baja_matriculados(con, carpeta):
    kpi = con.sql("SELECT * FROM kpi_campania").df().set_index("campania")
    for c in kpi.index:
        r = reporte(carpeta / "crudo" / c, c)
        assert r.postulantes > kpi.loc[c, "postulantes"]
        assert r.ingresantes >= kpi.loc[c, "ingresantes"]
        assert r.matriculados < kpi.loc[c, "matriculados"]
        assert r.por_modalidad["postulantes"].sum() == r.postulantes
