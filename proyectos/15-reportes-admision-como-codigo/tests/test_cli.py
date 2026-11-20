from admision import cli


def test_probar_sale_con_cero_en_datos_limpios(carpeta, monkeypatch):
    monkeypatch.setattr(cli, "CRUDO", carpeta / "crudo")
    monkeypatch.setattr(cli, "DATOS", carpeta)
    assert cli.main(["probar"]) == 0


def test_probar_sale_con_uno_si_falta_un_archivo(carpeta, tmp_path, monkeypatch):
    import shutil
    copia = tmp_path / "crudo"
    shutil.copytree(carpeta / "crudo", copia)
    (copia / "2027-1" / "tesoreria_pagos_2027-1.xlsx").unlink()
    monkeypatch.setattr(cli, "CRUDO", copia)
    monkeypatch.setattr(cli, "DATOS", tmp_path)
    assert cli.main(["probar"]) == 1
