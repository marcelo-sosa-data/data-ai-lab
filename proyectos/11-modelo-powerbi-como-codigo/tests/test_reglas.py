from semantico.reglas import hay_errores, revisar, revisar_medidas
from semantico.tmdl import modelo_desde_textos


def test_el_modelo_no_tiene_hallazgos(modelo, casos):
    assert revisar(modelo, {c.medida for c in casos}) == []


def _modelo(medidas: str, rel_extra: str = "", particion: str = 'RutaDatos & "/t.parquet"'):
    return modelo_desde_textos({
        "tables/T.tmdl": "table T\n" + medidas +
                         "\tcolumn id_x\n\t\tdataType: int64\n\t\tsummarizeBy: sum\n"
                         "\tcolumn v\n\t\tdataType: int64\n"
                         f"\tpartition T = m\n\t\tsource = {particion}\n",
        "tables/D.tmdl": "table D\n\tcolumn id_x\n\t\tdataType: int64\n\t\tisHidden\n\t\tsummarizeBy: none\n"
                         f"\tpartition D = m\n\t\tsource = {particion}\n",
        "relationships.tmdl": "relationship r\n\tfromColumn: T.id_x\n\ttoColumn: D.id_x\n" + rel_extra,
    })


def test_cada_regla_salta():
    medidas = (
        "\tmeasure Sin = SUM ( T[v] ) / 2\n"
        "\t/// ok\n\tmeasure '% algo' = SUM ( T[nada] ) + [Otra]\n\t\tformatString: 0.0\n\t\tdisplayFolder: X\n"
        "\t/// fija\n\tmeasure Fija = CALCULATE ( SUM ( T[v] ), T[v] = \"2025-2\" )\n"
        "\t\tformatString: 0\n\t\tdisplayFolder: X\n"
        "\t/// rota\n\tmeasure Rota = SUM ( T[v]\n\t\tformatString: 0\n\t\tdisplayFolder: X\n"
    )
    m = _modelo(medidas, "\tcrossFilteringBehavior: bothDirections\n", '"C:\\datos\\t.parquet"')
    reglas = {h.regla for h in revisar(m, medidas_probadas={"Sin"})}
    assert {"R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "R11", "R12", "R13",
            "R14"} <= reglas


def test_avisos_no_bloquean():
    m = _modelo("\t/// d\n\tmeasure '% x' = DIVIDE ( 1, 2 )\n\t\tformatString: 0.00\n\t\tdisplayFolder: X\n")
    hallazgos = revisar_medidas(m)
    assert [h.regla for h in hallazgos] == ["R03"]
    assert not hay_errores(hallazgos)
