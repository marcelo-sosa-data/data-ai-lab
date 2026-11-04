"""Contrato de datos en YAML: esquema de plata y validación de cada evento del CDC en SQL."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, Field, model_validator
from pyiceberg.schema import Schema
from pyiceberg.types import (DateType, DoubleType, IntegerType, LongType, NestedField, StringType,
                             TimestampType)

from .rutas import RAIZ, ruta_contrato

Tipo = Literal["long", "int", "string", "double", "timestamp", "date"]

TIPOS_ICEBERG = {"long": LongType(), "int": IntegerType(), "string": StringType(), "double": DoubleType(),
                 "timestamp": TimestampType(), "date": DateType()}
TIPOS_DUCKDB = {"long": "BIGINT", "int": "INTEGER", "string": "VARCHAR", "double": "DOUBLE",
                "timestamp": "TIMESTAMP", "date": "DATE"}


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


class Columna(BaseModel):
    tipo: Tipo
    requerido: bool = False
    valores: list[str] | None = None
    valores_de: str | None = None
    patron: str | None = None
    minimo: float | None = None
    maximo: float | None = None
    desde: str = "1.0.0"


class Regla(BaseModel):
    nombre: str
    sql: str
    columnas: list[str]
    descripcion: str = ""


class Contrato(BaseModel):
    contrato: str
    version: str
    dueno: str
    consumidor: str
    fuente: str
    versiones: dict[str, date] = Field(default_factory=dict)
    clave: str
    particion: str
    columnas: dict[str, Columna]
    reglas: list[Regla] = Field(default_factory=list)
    columnas_historial: list[str]
    umbral_cuarentena: float = 0.02

    @model_validator(mode="after")
    def _referencias(self):
        faltan = [c for c in [self.clave, self.particion, *self.columnas_historial] if c not in self.columnas]
        faltan += [c for r in self.reglas for c in r.columnas if c not in self.columnas]
        if faltan:
            raise ValueError(f"el contrato usa columnas que no declara: {sorted(set(faltan))}")
        if not self.columnas[self.clave].requerido:
            raise ValueError("la clave tiene que ser requerida")
        return self

    @classmethod
    def desde_yaml(cls, ruta: Path | None = None) -> "Contrato":
        ruta = Path(ruta or ruta_contrato())
        return cls.model_validate(yaml.safe_load(ruta.read_text(encoding="utf-8")))

    def vigente(self, dia: date) -> "Contrato":
        """El contrato con la versión que regía ese día (las columnas de versiones futuras no cuentan)."""
        if not self.versiones:
            return self
        validas = [v for v, d in self.versiones.items() if d <= dia and _version(v) <= _version(self.version)]
        if not validas:
            raise ValueError(f"no hay versión del contrato vigente al {dia}")
        return self.model_copy(update={"version": max(validas, key=_version)})

    # ------------------------------------------------------------------ esquema

    def activas(self) -> dict[str, Columna]:
        """Columnas vigentes en esta versión del contrato."""
        v = _version(self.version)
        return {n: c for n, c in self.columnas.items() if _version(c.desde) <= v}

    def esquema(self, extra: list[NestedField] | None = None) -> Schema:
        """Esquema Iceberg de plata: las columnas del contrato más las de control."""
        campos = []
        for i, (nombre, col) in enumerate(self.activas().items(), start=1):
            campos.append(NestedField(i, nombre, TIPOS_ICEBERG[col.tipo], required=nombre == self.clave))
        for j, f in enumerate(extra or [], start=len(campos) + 1):
            campos.append(NestedField(j, f.name, f.field_type, required=f.required))
        return Schema(*campos, identifier_field_ids=[1])

    def valores_permitidos(self, col: Columna) -> list[str] | None:
        if col.valores is not None:
            return col.valores
        if col.valores_de:
            return list(pd.read_csv(RAIZ / col.valores_de)["distrito"])
        return None

    # ------------------------------------------------------------------ validación

    def sql_columnas(self, imagen: str = "img") -> str:
        """Extrae cada columna del JSON con su tipo (TRY_CAST: un tipo malo queda NULL)."""
        partes = []
        for n, c in self.activas().items():
            partes.append(f"TRY_CAST(json_extract_string({imagen}, '$.{n}') AS {TIPOS_DUCKDB[c.tipo]}) AS {n}")
        return ",\n       ".join(partes)

    def chequeos(self) -> list[tuple[str, str, list[str]]]:
        """(nombre, condición que indica violación, columnas) para cada regla del contrato."""
        salida = []
        for n, c in self.activas().items():
            crudo = f"json_extract_string(img, '$.{n}')"
            salida.append((f"{n}.tipo", f"{crudo} IS NOT NULL AND {n} IS NULL", [n]))
            if c.requerido:
                salida.append((f"{n}.requerido", f"{crudo} IS NULL", [n]))
            permitidos = self.valores_permitidos(c)
            if permitidos is not None:
                lista = ", ".join("'" + v.replace("'", "''") + "'" for v in permitidos)
                salida.append((f"{n}.valores", f"{n} NOT IN ({lista})", [n]))
            if c.patron:
                salida.append((f"{n}.patron", f"NOT regexp_full_match({n}, '{c.patron}')", [n]))
            if c.minimo is not None:
                salida.append((f"{n}.minimo", f"{n} < {c.minimo}", [n]))
            if c.maximo is not None:
                salida.append((f"{n}.maximo", f"{n} > {c.maximo}", [n]))
        for r in self.reglas:
            salida.append((r.nombre, f"NOT ({r.sql})", r.columnas))
        return salida

    def sql_validacion(self, tabla: str) -> str:
        """SQL (DuckDB) que tipa cada evento y lista las reglas que rompe.

        `tabla` necesita: lote, lsn, op, ts_commit, id_envio, antes, despues. En un borrado
        solo se exige la clave; la imagen que se valida es `despues` (o `antes` si es `d`).
        """
        casos = []
        historial = []
        for nombre, cond, cols in self.chequeos():
            guarda = "op <> 'd' AND " if nombre != f"{self.clave}.requerido" else ""
            casos.append(f"CASE WHEN {guarda}({cond}) THEN '{nombre}' END")
            if set(cols) & set(self.columnas_historial):
                historial.append(f"CASE WHEN {guarda}({cond}) THEN '{nombre}' END")
        return f"""
WITH base AS (
  SELECT *, COALESCE(despues, antes)::JSON AS img FROM {tabla}
), tipado AS (
  SELECT base.*,
       {self.sql_columnas()},
       json_extract_string(antes, '$.estado') AS estado_antes
  FROM base
)
SELECT * EXCLUDE (img),
       list_filter([{', '.join(casos)}], lambda x: x IS NOT NULL) AS violaciones,
       len(list_filter([{', '.join(historial) or 'NULL'}], lambda x: x IS NOT NULL)) = 0 AS valido_historial
FROM tipado
"""

    def sql_no_declaradas(self, tabla: str) -> str:
        """Llaves que llegan en el JSON y el contrato no declara (o no tiene vigentes)."""
        declaradas = ", ".join(f"'{c}'" for c in self.activas())
        return f"""
SELECT k AS columna, COUNT(*) AS eventos, MIN(lote) AS primer_lote
FROM (SELECT unnest(json_keys(despues::JSON)) AS k, lote FROM {tabla} WHERE despues IS NOT NULL)
WHERE k NOT IN ({declaradas})
GROUP BY 1 ORDER BY 1
"""
