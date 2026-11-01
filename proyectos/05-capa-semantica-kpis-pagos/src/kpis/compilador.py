"""
Compila una consulta de métricas (métricas + dimensiones + grano + filtros) a SQL.

El SQL se arma en dialecto DuckDB y sqlglot lo traduce a otros motores. Dos reglas
que la capa garantiza para que nadie tenga que acordarse:

  - los ratios se calculan como suma del numerador sobre suma del denominador en el
    grano pedido, nunca como promedio de ratios diarios
  - las medidas salen de la tabla de hechos y las dimensiones de otros modelos entran
    por LEFT JOIN a su llave primaria: no se duplican filas ni se pierden cobros
    de comercios que no están en el maestro (quedan como '(sin dato)')
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sqlglot
from sqlglot import exp

from .modelo import Definicion, ErrorSemantico

GRANOS = {"dia": None, "semana": "WEEK", "mes": "MONTH", "trimestre": "QUARTER", "anio": "YEAR"}
DIALECTOS = ["duckdb", "snowflake", "bigquery", "postgres"]
SIN_DATO = "(sin dato)"


@dataclass
class Consulta:
    metricas: list[str]
    dimensiones: list[str] = field(default_factory=list)
    grano: str | None = None
    desde: date | str | None = None
    hasta: date | str | None = None
    filtros: dict[str, list] = field(default_factory=dict)
    incluir_medidas: bool = False  # devuelve también numeradores y denominadores


def _calificar(expr: str, alias: str) -> exp.Expression:
    """Parsea una expresión del YAML y le pone el alias de su tabla a cada columna."""
    arbol = sqlglot.parse_one(expr, read="duckdb")
    for col in arbol.find_all(exp.Column):
        if not col.table:
            col.set("table", exp.to_identifier(alias))
    return arbol


def _literal(v) -> exp.Expression:
    return exp.Literal.number(v) if isinstance(v, (int, float)) else exp.Literal.string(str(v))


class Compilador:
    def __init__(self, definicion: Definicion):
        self.d = definicion

    # ---------------------------------------------------------------- piezas

    def _dimension(self, nombre: str) -> exp.Expression:
        modelo = self.d.modelo_de_dimension(nombre)
        e = _calificar(self.d.modelos[modelo].dimensiones[nombre].expr, modelo)
        if modelo != self.d.hechos:
            # LEFT JOIN: un cobro sin comercio en el maestro no se pierde, queda como '(sin dato)'
            e = exp.func("COALESCE", exp.cast(e, "VARCHAR"), exp.Literal.string(SIN_DATO))
        return e

    def _medida(self, nombre: str) -> exp.Expression:
        m = self.d.medidas[nombre]
        valor = _calificar(m.expr, m.modelo) if m.expr else exp.Literal.number(1)
        if m.filtro:
            valor = exp.Case(ifs=[exp.If(this=_calificar(m.filtro, m.modelo), true=valor)])
        if m.agregacion == "count":
            return exp.Count(this=valor if m.filtro else exp.Star())
        if m.agregacion == "sum":
            return exp.Sum(this=valor)
        return exp.Count(this=exp.Distinct(expressions=[valor]))

    def expresion_metrica(self, nombre: str) -> exp.Expression:
        """Expresión de la métrica sobre las columnas de medidas del CTE `base`."""
        m = self.d.metrica(nombre)
        if m.tipo == "simple":
            return exp.column(m.medida)
        if m.tipo == "ratio":
            return exp.Div(this=exp.cast(exp.column(m.numerador), "DOUBLE"),
                           expression=exp.func("NULLIF", exp.column(m.denominador), exp.Literal.number(0)))
        arbol = sqlglot.parse_one(m.expr, read="duckdb")

        def reemplazar(nodo):
            if isinstance(nodo, exp.Column) and nodo.name in self.d.metricas:
                return exp.paren(self.expresion_metrica(nodo.name))
            if isinstance(nodo, exp.Div):  # división segura y en punto flotante
                return exp.Div(this=exp.cast(nodo.this, "DOUBLE"),
                               expression=exp.func("NULLIF", nodo.expression, exp.Literal.number(0)))
            return nodo

        return arbol.transform(reemplazar)

    # ---------------------------------------------------------------- consulta

    def compilar(self, c: Consulta, dialecto: str = "duckdb", legible: bool = True) -> str:
        if dialecto not in DIALECTOS:
            raise ErrorSemantico(f"dialecto {dialecto} no soportado. Usa: {', '.join(DIALECTOS)}")
        arbol = self.arbol(c)
        if dialecto == "bigquery" and c.grano == "semana":
            # en BigQuery WEEK empieza el domingo; DuckDB, Snowflake y Postgres usan lunes (ISO)
            for dt in arbol.find_all(exp.DateTrunc):
                dt.set("unit", exp.var("ISOWEEK"))
        return arbol.sql(dialect=dialecto, pretty=legible)

    def arbol(self, c: Consulta) -> exp.Select:
        if not c.metricas:
            raise ErrorSemantico("la consulta necesita al menos una métrica")
        if c.grano is not None and c.grano not in GRANOS:
            raise ErrorSemantico(f"grano {c.grano} no soportado. Usa: {', '.join(GRANOS)}")
        hechos = self.d.hechos
        mod_hechos = self.d.modelos[hechos]

        medidas: list[str] = []
        for m in c.metricas:
            medidas += [x for x in self.d.medidas_de(m) if x not in medidas]

        claves: list[tuple[str, exp.Expression]] = []
        if c.grano:
            if not mod_hechos.tiempo:
                raise ErrorSemantico(f"el modelo {hechos} no tiene columna de tiempo")
            t = exp.column(mod_hechos.tiempo, table=hechos)
            unidad = GRANOS[c.grano]
            claves.append(("periodo", exp.cast(t, "DATE") if unidad is None else exp.cast(
                exp.DateTrunc(this=t, unit=exp.var(unidad)), "DATE")))
        for d in c.dimensiones:
            claves.append((d, self._dimension(d)))

        base = exp.select(*[e.copy().as_(n) for n, e in claves],
                          *[self._medida(m).as_(m) for m in medidas]).from_(
            exp.to_table(mod_hechos.tabla).as_(hechos))

        usados = set(c.dimensiones) | set(c.filtros)
        for nm in sorted({self.d.modelo_de_dimension(d) for d in usados} - {hechos}):
            entidad = self._entidad_comun(nm)
            base = base.join(
                exp.to_table(self.d.modelos[nm].tabla).as_(nm), join_type="left",
                on=exp.EQ(this=exp.column(mod_hechos.entidades[entidad].columna, table=hechos),
                          expression=exp.column(self.d.modelos[nm].entidades[entidad].columna, table=nm)))

        condiciones = []
        if c.desde or c.hasta:
            t = exp.column(mod_hechos.tiempo, table=hechos)
            if c.desde:
                condiciones.append(exp.GTE(this=t.copy(), expression=exp.cast(exp.Literal.string(str(c.desde)), "DATE")))
            if c.hasta:
                condiciones.append(exp.LTE(this=t.copy(), expression=exp.cast(exp.Literal.string(str(c.hasta)), "DATE")))
        for d, valores in c.filtros.items():
            valores = valores if isinstance(valores, (list, tuple)) else [valores]
            condiciones.append(exp.In(this=self._dimension(d), expressions=[_literal(v) for v in valores]))
        if condiciones:
            base = base.where(exp.and_(*condiciones))
        if claves:
            base = base.group_by(*[exp.Literal.number(i + 1) for i in range(len(claves))])

        columnas = [exp.column(n) for n, _ in claves]
        columnas += [self.expresion_metrica(m).as_(m) for m in c.metricas]
        if c.incluir_medidas:
            columnas += [exp.column(m) for m in medidas if m not in c.metricas]
        final = exp.select(*columnas).from_("base").with_("base", as_=base)
        if claves:
            final = final.order_by(*[exp.column(n) for n, _ in claves])
        return final

    def _entidad_comun(self, modelo: str) -> str:
        foraneas = {e for e, x in self.d.modelos[self.d.hechos].entidades.items() if x.tipo == "foranea"}
        primarias = {e for e, x in self.d.modelos[modelo].entidades.items() if x.tipo == "primaria"}
        comunes = sorted(foraneas & primarias)
        if not comunes:
            raise ErrorSemantico(f"no hay cómo unir {modelo} con {self.d.hechos}")
        return comunes[0]
