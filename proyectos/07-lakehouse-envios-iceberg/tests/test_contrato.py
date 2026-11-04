import duckdb
import pyarrow as pa
import pytest
from pydantic import ValidationError

from lakehouse.contrato import Contrato
from conftest import evento, fila
import json


def _validar(contrato, eventos):
    filas = [{"lote": "x", "lsn": e["lsn"], "op": e["op"], "ts_commit": None, "id_envio": 1,
              "antes": json.dumps(e["antes"]) if e["antes"] else None,
              "despues": json.dumps(e["despues"]) if e["despues"] else None} for e in eventos]
    con = duckdb.connect()
    con.register("t", pa.Table.from_pylist(filas))
    return con.sql(contrato.sql_validacion("t")).df()


def test_carga_y_esquema(contrato):
    assert contrato.version == "1.1.0" and contrato.clave == "id_envio"
    esquema = contrato.esquema()
    assert esquema.find_field("id_envio").required
    assert "franja_horaria" in esquema.column_names


def test_columna_nueva_depende_de_la_version(contrato):
    viejo = contrato.model_copy(update={"version": "1.0.0"})
    assert "franja_horaria" not in viejo.activas()
    assert "franja_horaria" not in viejo.esquema().column_names


def test_contrato_con_referencia_rota_no_carga(contrato):
    datos = contrato.model_dump()
    datos["columnas_historial"] = ["id_envio", "no_existe"]
    with pytest.raises(ValidationError, match="no_existe"):
        Contrato.model_validate(datos)


@pytest.mark.parametrize("cambio,regla", [
    ({"peso_kg": 1500.0}, "peso_kg.maximo"),
    ({"distrito": "Surco"}, "distrito.valores"),
    ({"distrito": "Miraflores "}, "distrito.valores"),
    ({"estado": "EN_RUTA"}, "estado.valores"),
    ({"intentos": "dos"}, "intentos.tipo"),
    ({"servicio": None}, "servicio.requerido"),
    ({"codigo_seguimiento": "XX123"}, "codigo_seguimiento.patron"),
    ({"estado": "entregado", "entregado_en": None}, "entregado_con_hora"),
    ({"fecha_promesa": "2026-08-01"}, "promesa_no_antes_del_registro"),
    ({"franja_horaria": "madrugada"}, "franja_horaria.valores"),
])
def test_cada_regla_se_detecta(contrato, cambio, regla):
    df = _validar(contrato, [evento(1, "u", fila(**cambio))])
    assert list(df.loc[0, "violaciones"]) == [regla]


def test_evento_sano_no_tiene_violaciones(contrato):
    df = _validar(contrato, [evento(1, "c", fila()),
                             evento(2, "u", fila(estado="entregado", entregado_en="2026-08-04 11:00:00"))])
    assert all(len(v) == 0 for v in df["violaciones"])
    assert df["valido_historial"].all()


def test_peso_malo_no_invalida_el_historial(contrato):
    df = _validar(contrato, [evento(1, "u", fila(peso_kg=2500.0)), evento(2, "u", fila(estado="EN_RUTA"))])
    assert list(df["valido_historial"]) == [True, False]


def test_borrado_solo_exige_la_clave(contrato):
    df = _validar(contrato, [evento(1, "d", None, antes=fila(peso_kg=9999.0))])
    assert len(df.loc[0, "violaciones"]) == 0


def test_columnas_no_declaradas(contrato):
    filas = [{"lote": "2026-08-03T12", "despues": json.dumps(fila(color="rojo"))}]
    con = duckdb.connect()
    con.register("t", pa.Table.from_pylist(filas))
    assert con.sql(contrato.sql_no_declaradas("t")).fetchall() == [("color", 1, "2026-08-03T12")]
