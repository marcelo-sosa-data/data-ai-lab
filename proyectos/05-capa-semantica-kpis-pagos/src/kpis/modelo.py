"""
Esquema de la capa semántica (modelos, medidas y métricas) y su carga desde YAML.

La validación de este módulo es estática: tipos, referencias entre medidas y métricas,
ciclos en métricas derivadas y que cada dimensión tenga cómo unirse a la tabla de hechos.
Lo que depende de la base (tablas, columnas, conciliación) está en `validacion.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp

FORMATOS = Literal["soles", "soles_decimal", "entero", "porcentaje", "porcentaje_fino"]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entidad(Base):
    columna: str
    tipo: Literal["primaria", "foranea"]


class Dimension(Base):
    expr: str
    descripcion: str = ""
    explicable: bool = True  # False: es un resultado (estado), no una causa
    deriva: bool = False     # True: su mezcla cambia sola con el tiempo (versiones, cohortes)


class Modelo(Base):
    tabla: str
    descripcion: str = ""
    tiempo: str | None = None
    entidades: dict[str, Entidad] = Field(default_factory=dict)
    dimensiones: dict[str, Dimension] = Field(default_factory=dict)


class Medida(Base):
    modelo: str
    agregacion: Literal["count", "sum", "count_distinct"]
    expr: str | None = None
    filtro: str | None = None
    descripcion: str = ""

    @property
    def aditiva(self) -> bool:
        """Se puede sumar entre segmentos y periodos. Un conteo de distintos, no."""
        return self.agregacion != "count_distinct"

    @model_validator(mode="after")
    def _expr_requerida(self):
        if self.agregacion != "count" and not self.expr:
            raise ValueError(f"la agregación {self.agregacion} necesita expr")
        return self


class Monitor(Base):
    modelo: Literal["multiplicativo", "aditivo"]
    umbral_minimo: float


class Metrica(Base):
    tipo: Literal["simple", "ratio", "derivada"]
    medida: str | None = None
    numerador: str | None = None
    denominador: str | None = None
    expr: str | None = None
    etiqueta: str
    descripcion: str = ""
    formato: FORMATOS = "entero"
    responsable: str = ""
    monitor: Monitor | None = None

    @model_validator(mode="after")
    def _campos_por_tipo(self):
        requeridos = {"simple": ["medida"], "ratio": ["numerador", "denominador"], "derivada": ["expr"]}
        faltan = [c for c in requeridos[self.tipo] if not getattr(self, c)]
        if faltan:
            raise ValueError(f"una métrica {self.tipo} necesita {', '.join(faltan)}")
        return self


class ErrorSemantico(ValueError):
    """Definición inválida o consulta que la capa no puede resolver."""


class Definicion(Base):
    modelos: dict[str, Modelo]
    medidas: dict[str, Medida]
    metricas: dict[str, Metrica]

    @model_validator(mode="after")
    def _referencias(self):
        errores = []
        for n, m in self.medidas.items():
            if m.modelo not in self.modelos:
                errores.append(f"medida {n}: el modelo {m.modelo} no existe")
        hechos = {m.modelo for m in self.medidas.values()}
        if len(hechos) > 1:
            errores.append(f"todas las medidas deben salir de una sola tabla de hechos; hay {sorted(hechos)}")
        for n, met in self.metricas.items():
            for campo in ("medida", "numerador", "denominador"):
                ref = getattr(met, campo)
                if ref and ref not in self.medidas:
                    errores.append(f"métrica {n}: la medida {ref} no existe")
            if met.tipo == "derivada":
                for ref in referencias_derivada(met.expr):
                    if ref not in self.metricas:
                        errores.append(f"métrica {n}: la métrica {ref} no existe")
        vistos: dict[str, str] = {}
        for nm, mod in self.modelos.items():
            for d in mod.dimensiones:
                if d in vistos:
                    errores.append(f"la dimensión {d} está en {vistos[d]} y en {nm}")
                vistos[d] = nm
        if errores:
            raise ErrorSemantico("; ".join(errores))
        self._sin_ciclos()
        if len(hechos) == 1:
            self._joins_resolubles(hechos.pop())
        return self

    def _sin_ciclos(self) -> None:
        estado: dict[str, int] = {}

        def visitar(n: str, camino: list[str]) -> None:
            if estado.get(n) == 1:
                raise ErrorSemantico(f"ciclo en métricas derivadas: {' -> '.join(camino + [n])}")
            if estado.get(n) == 2:
                return
            estado[n] = 1
            m = self.metricas[n]
            if m.tipo == "derivada":
                for ref in referencias_derivada(m.expr):
                    visitar(ref, camino + [n])
            estado[n] = 2

        for n in self.metricas:
            visitar(n, [])

    def _joins_resolubles(self, hechos: str) -> None:
        foraneas = {e for e, ent in self.modelos[hechos].entidades.items() if ent.tipo == "foranea"}
        for nm, mod in self.modelos.items():
            if nm == hechos or not mod.dimensiones:
                continue
            primarias = {e for e, ent in mod.entidades.items() if ent.tipo == "primaria"}
            if not primarias & foraneas:
                raise ErrorSemantico(f"el modelo {nm} no comparte una entidad con {hechos}: "
                                     "sus dimensiones no se pueden usar")

    # ------------------------------------------------------------------ utilidades

    @property
    def hechos(self) -> str:
        return next(iter(self.medidas.values())).modelo

    def modelo_de_dimension(self, dim: str) -> str:
        for nm, mod in self.modelos.items():
            if dim in mod.dimensiones:
                return nm
        raise ErrorSemantico(f"la dimensión {dim} no existe. Hay: {', '.join(self.dimensiones())}")

    def dimensiones(self) -> list[str]:
        return [d for mod in self.modelos.values() for d in mod.dimensiones]

    def dimension(self, nombre: str) -> Dimension:
        return self.modelos[self.modelo_de_dimension(nombre)].dimensiones[nombre]

    def metrica(self, nombre: str) -> Metrica:
        if nombre not in self.metricas:
            raise ErrorSemantico(f"la métrica {nombre} no existe. Hay: {', '.join(self.metricas)}")
        return self.metricas[nombre]

    def medidas_de(self, nombre: str) -> list[str]:
        """Medidas que necesita una métrica, resolviendo las derivadas."""
        m = self.metrica(nombre)
        if m.tipo == "simple":
            return [m.medida]
        if m.tipo == "ratio":
            return [m.numerador, m.denominador]
        salida: list[str] = []
        for ref in referencias_derivada(m.expr):
            salida += [x for x in self.medidas_de(ref) if x not in salida]
        return salida


def referencias_derivada(expr: str) -> list[str]:
    """Nombres de métricas que usa la expresión de una métrica derivada."""
    arbol = sqlglot.parse_one(expr, read="duckdb")
    return list(dict.fromkeys(c.name for c in arbol.find_all(exp.Column)))


def cargar(ruta: str | Path) -> Definicion:
    with open(ruta, encoding="utf-8") as f:
        crudo = yaml.safe_load(f)
    try:
        return Definicion.model_validate(crudo)
    except ErrorSemantico:
        raise
    except ValueError as e:  # pydantic envuelve los errores de los validadores
        raise ErrorSemantico(str(e)) from e
