"""
El reporte de hoy, reproducido en Python para poder compararlo.

Cada lunes el analista de Admisión pega los tres exports en un Excel maestro
y la hoja Resumen cuenta con CONTAR.SI.CONJUNTO sobre una lista fija de
modalidades, sedes y carreras:

  - Postulantes: filas del export con estado distinto de Anulado
  - Ingresantes: filas con estado Ingresó
  - Matriculados: ingresantes cuyo VALOR(documento) aparece con BUSCARV en
    el documento del pagador de algún pago cuyo concepto contiene "MATRICULA"
  - Interesados: filas del export del CRM
  - Pendientes: ingresantes cuyo BUSCARV da #N/A; es la lista que se llama

Las hojas BD_ leen las columnas por posición (A, B, C...), como las
fórmulas del Excel, y los criterios ya incluyen la escritura vieja y la
nueva de cada modalidad y estado. No hay ningún control antes de enviar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import catalogos as K
from .lectura import _leer_csv
from .normalizar import clave

# posiciones de columna del export de admisión que usan las fórmulas
COL_CODIGO, COL_DOCUMENTO, COL_NOMBRE, COL_MODALIDAD, COL_CARRERA, COL_SEDE, COL_ESTADO = 0, 2, 3, 5, 6, 7, 9
# y del reporte de tesorería
COL_DOC_PAGADOR, COL_CONCEPTO = 1, 3


@dataclass
class ReporteActual:
    campania: str
    interesados: int
    postulantes: int
    ingresantes: int
    matriculados: int
    por_modalidad: pd.DataFrame
    por_sede: pd.DataFrame
    por_carrera: pd.DataFrame
    pendientes: pd.DataFrame


def _valor(texto) -> int | None:
    """VALOR() de Excel: acepta espacios a los lados, no letras ni espacios al medio."""
    t = str(texto).strip()
    if t.endswith(".0"):
        t = t[:-2]
    return int(t) if t.isdigit() else None


def reporte(carpeta_campania: Path, campania: str) -> ReporteActual:
    carpeta = Path(carpeta_campania)
    adm = _leer_csv(carpeta / f"admision_inscripciones_{campania}.csv")
    tes = pd.read_excel(carpeta / f"tesoreria_pagos_{campania}.xlsx", dtype=object)
    crm = pd.read_excel(carpeta / f"crm_interesados_{campania}.xlsx", dtype=object)

    filas = pd.DataFrame({
        "codigo": adm.iloc[:, COL_CODIGO], "documento": adm.iloc[:, COL_DOCUMENTO],
        "nombre": adm.iloc[:, COL_NOMBRE], "modalidad": adm.iloc[:, COL_MODALIDAD].map(clave),
        "sede": adm.iloc[:, COL_SEDE].map(clave), "carrera": adm.iloc[:, COL_CARRERA].map(clave),
        "estado": adm.iloc[:, COL_ESTADO].map(clave),
    })
    modalidades = [clave(m) for m in K.MODALIDADES]
    sedes = [clave(s) for s in K.SEDES]
    # CONTAR.SI.CONJUNTO solo suma lo que está en la lista de la hoja Resumen
    en_lista = filas["modalidad"].isin(modalidades) & filas["sede"].isin(sedes)
    postulan = en_lista & (filas["estado"] != "ANULADO")
    ingresan = en_lista & (filas["estado"] == "INGRESO")

    concepto = tes.iloc[:, COL_CONCEPTO].astype("string").str.upper()
    es_matricula = concepto.str.contains("MATRICULA", regex=False, na=False)
    pagadores = {v for v in tes.loc[es_matricula].iloc[:, COL_DOC_PAGADOR].map(_valor) if v is not None}
    filas["matriculado"] = ingresan & filas["documento"].map(lambda d: _valor(d) in pagadores)

    def contar(columna, lista):
        return pd.DataFrame({
            columna: lista,
            "postulantes": [int((postulan & (filas[columna] == v)).sum()) for v in lista],
            "ingresantes": [int((ingresan & (filas[columna] == v)).sum()) for v in lista],
            "matriculados": [int((filas["matriculado"] & (filas[columna] == v)).sum()) for v in lista],
        })

    pendientes = filas.loc[ingresan & ~filas["matriculado"], ["codigo", "documento", "nombre", "modalidad", "sede"]]
    return ReporteActual(
        campania=campania,
        interesados=len(crm),
        postulantes=int(postulan.sum()),
        ingresantes=int(ingresan.sum()),
        matriculados=int(filas["matriculado"].sum()),
        por_modalidad=contar("modalidad", modalidades),
        por_sede=contar("sede", sedes),
        por_carrera=contar("carrera", [clave(c) for c in K.CARRERAS]),
        pendientes=pendientes.reset_index(drop=True),
    )
