"""
Arma la base que lee el sitio de Evidence. Solo se escribe si las pruebas no
tienen errores: si algo bloquea, el sitio se queda con la última versión buena.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from . import catalogos as K
from .modelo import TABLAS_REPORTE
from .pruebas import Resultado

RAIZ = Path(__file__).parents[2]
DESTINO = RAIZ / "reportes" / "sources" / "admision" / "admision.duckdb"
VERSION_ALMACENAMIENTO = "v1.1.0"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def etiqueta_dia(d) -> str:
    """date(2026, 11, 15) -> '15 nov'."""
    d = pd.Timestamp(d)
    return f"{d.day} {MESES[d.month - 1]}"


def etiqueta_fecha(d) -> str:
    """date(2026, 11, 15) -> '15 nov 2026'."""
    d = pd.Timestamp(d)
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def avance_comparado(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Campaña en curso y su comparable, alineadas por semana, con la fecha de la actual en el eje."""
    par = con.sql("""
        SELECT codigo, anterior_comparable, semana_corte FROM campanias
        WHERE codigo = (SELECT campania_actual FROM parametros)
    """).fetchall()[0]
    actual, anterior, semanas = par
    df = con.sql(f"""
        SELECT campania, semana, fin_semana, postulantes, postulantes_acum, ingresantes_acum, matriculados_acum
        FROM avance_semanal WHERE campania IN ('{actual}', '{anterior}') AND semana <= {semanas}
        ORDER BY campania, semana
    """).df()
    fechas = df[df["campania"] == actual].set_index("semana")["fin_semana"]
    df["etiqueta"] = df["semana"].map(lambda s: etiqueta_dia(fechas[s]))
    df["serie"] = df["campania"].map({actual: f"{actual} (actual)", anterior: f"{anterior} (misma semana)"})
    return df


def resultados_a_tabla(resultados: list[Resultado]) -> pd.DataFrame:
    return pd.DataFrame([{
        "prueba": r.nombre, "severidad": r.severidad, "descripcion": r.descripcion, "filas": r.filas,
        "estado": "aprobada" if r.aprobada else ("error" if r.severidad == "error" else "aviso"),
        "detalle": r.error_sql or (json.dumps(r.muestra[0], ensure_ascii=False) if r.muestra else ""),
    } for r in resultados])


def publicar(con: duckdb.DuckDBPyConnection, resultados: list[Resultado], destino: Path = DESTINO,
             extras: dict[str, pd.DataFrame] | None = None) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp.duckdb")
    temporal.unlink(missing_ok=True)
    salida = duckdb.connect()
    # el conector de Evidence trae un DuckDB anterior: se escribe en un formato que pueda leer
    salida.execute(f"ATTACH '{temporal}' AS sitio (STORAGE_VERSION '{VERSION_ALMACENAMIENTO}')")

    tablas = {t: con.sql(f"SELECT * FROM {t}").df() for t in TABLAS_REPORTE}
    kpi = tablas["kpi_campania"]
    kpi["corte_texto"] = kpi["corte"].map(etiqueta_fecha)
    av = tablas["avance_semanal"]
    av["etiqueta"] = av["fin_semana"].map(etiqueta_dia)
    tablas["avance_comparado"] = avance_comparado(con)
    tablas["resultados_pruebas"] = resultados_a_tabla(resultados)
    tablas["publicacion"] = pd.DataFrame([{
        "campania_actual": K.CAMPANIA_ACTUAL,
        "corte": con.sql("SELECT corte FROM parametros").fetchall()[0][0],
        "corte_texto": etiqueta_fecha(con.sql("SELECT corte FROM parametros").fetchall()[0][0]),
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pruebas": len(resultados),
        "pruebas_aprobadas": sum(r.aprobada for r in resultados),
        "avisos": sum((not r.aprobada) and r.severidad == "aviso" for r in resultados),
    }])
    for nombre, df in (extras or {}).items():
        tablas[nombre] = df
    for nombre, df in tablas.items():
        salida.register("_tmp", df)
        salida.execute(f"CREATE TABLE sitio.{nombre} AS SELECT * FROM _tmp")
        salida.unregister("_tmp")
    salida.close()
    shutil.move(temporal, destino)
    return destino
