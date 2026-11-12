"""
Motor local para evaluar las medidas DAX del modelo sobre los Parquet de origen.

Sirve para probar el modelo en CI sin Power BI: reproduce el contexto de filtro
de un visual (filtros + una columna de agrupación), la propagación de filtros
de las dimensiones a los hechos por las relaciones, CALCULATE con filtros
booleanos y REMOVEFILTERS/ALL, la transición de contexto al iterar con FILTER
o SUMX y las reglas de BLANK de DAX (BLANK + 1 = 1, BLANK < 0.4 es verdadero,
DIVIDE devuelve BLANK si el denominador es cero o vacío).

No es un motor DAX completo. Si una medida usa una función que no está aquí,
el motor lanza ErrorDAX y la prueba falla, en vez de dar un número inventado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .dax import (Binaria, Bloque, Columna, En, ErrorDAX, Funcion, Logico, Medida, Numero, Tabla,
                  Texto, Unaria, Variable, parsear)
from .tmdl import Modelo, archivo_parquet

BLANK = None


# ------------------------------------------------------------------ contexto

@dataclass(frozen=True)
class Contexto:
    """Contexto de evaluación: filtros por columna, filas en iteración y variables."""
    filtros: tuple = ()          # ((tabla, columna, frozenset(valores)), ...) ordenado
    filas: tuple = ()            # ((tabla, índice de fila), ...)
    variables: tuple = ()        # ((nombre, valor), ...)

    def filtros_dict(self) -> dict:
        return {(t, c): v for t, c, v in self.filtros}

    def con_filtros(self, filtros: dict) -> "Contexto":
        return Contexto(tuple(sorted(((t, c, v) for (t, c), v in filtros.items()),
                                     key=lambda x: (x[0], x[1]))), self.filas, self.variables)

    def con_fila(self, tabla: str, i: int) -> "Contexto":
        filas = tuple(f for f in self.filas if f[0] != tabla) + ((tabla, i),)
        return Contexto(self.filtros, filas, self.variables)

    def sin_filas(self) -> "Contexto":
        return Contexto(self.filtros, (), self.variables)

    def con_variable(self, nombre: str, valor) -> "Contexto":
        return Contexto(self.filtros, self.filas, self.variables + ((nombre, valor),))


@dataclass
class _Filas:
    """Resultado de una expresión de tabla: filas visibles de una tabla del modelo."""
    tabla: str
    indices: np.ndarray


def _normalizar(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _clave_igualdad(v):
    """Las comparaciones de texto en DAX no distinguen mayúsculas."""
    return v.casefold() if isinstance(v, str) else v


# ------------------------------------------------------------------ motor

@dataclass
class Motor:
    modelo: Modelo
    datos: dict[str, pd.DataFrame]
    _arboles: dict = field(default_factory=dict)
    _cache_visibles: dict = field(default_factory=dict)
    _indices_fk: dict = field(default_factory=dict)
    _cache_columnas: dict = field(default_factory=dict)
    _cache_arreglos: dict = field(default_factory=dict)
    _cache_distintos: dict = field(default_factory=dict)
    _cache_booleanos: dict = field(default_factory=dict)

    @classmethod
    def desde_carpeta(cls, modelo: Modelo, carpeta: str | Path) -> "Motor":
        """Carga cada tabla desde el Parquet que nombra su partición."""
        carpeta = Path(carpeta)
        datos = {}
        for nombre, t in modelo.tablas.items():
            archivo = archivo_parquet(t.particion)
            if archivo is None:
                raise ErrorDAX(f"La partición de {nombre} no lee un Parquet que el motor reconozca")
            df = pd.read_parquet(carpeta / archivo)
            faltan = [c.columna_origen for c in t.columnas.values() if c.columna_origen not in df.columns]
            if faltan:
                raise ErrorDAX(f"{archivo} no tiene las columnas {faltan} que pide la tabla {nombre}")
            datos[nombre] = pd.DataFrame(
                {c.nombre: df[c.columna_origen].to_numpy() for c in t.columnas.values()})
        return cls(modelo, datos)

    # ---------------------------------------------------------- API de alto nivel

    def evaluar(self, medida: str, filtros: dict | None = None, por: str | None = None) -> dict:
        """Evalúa una medida como en un visual: {valor de `por`: resultado}.

        filtros: {"Periodo[periodo]": "2026-2"} o con lista de valores.
        por: columna de agrupación ("Sede[sede]"); sin ella devuelve {None: total}.
        Como en un visual, los grupos con resultado BLANK no aparecen.
        """
        if medida not in self.modelo.medidas:
            raise ErrorDAX(f"La medida [{medida}] no existe en el modelo")
        base = {}
        for ref, valores in (filtros or {}).items():
            col = self._columna_texto(ref)
            valores = valores if isinstance(valores, (list, tuple, set)) else [valores]
            base[(col.tabla, col.columna)] = self._valores_que_coinciden(col, valores)
        ctx = Contexto().con_filtros(base)
        if por is None:
            v = self._medida(medida, ctx)
            return {} if v is BLANK else {None: v}
        col = self._columna_texto(por)
        visibles = self._visibles(col.tabla, ctx)
        salida = {}
        for valor in sorted(pd.unique(self._arr(col.tabla, col.columna)[visibles])):
            valor = _normalizar(valor)
            f = dict(base)
            f[(col.tabla, col.columna)] = frozenset([valor])
            v = self._medida(medida, ctx.con_filtros(f))
            if v is not BLANK:
                salida[valor] = v
        return salida

    # ---------------------------------------------------------- utilidades

    def _columna_texto(self, ref: str) -> Columna:
        arbol = parsear(ref)
        if not isinstance(arbol, Columna):
            raise ErrorDAX(f"{ref!r} no es una referencia a columna")
        self._validar_columna(arbol)
        return arbol

    def _validar_columna(self, col: Columna) -> None:
        if self.modelo.columna(col.tabla, col.columna) is None:
            raise ErrorDAX(f"La columna {col} no existe en el modelo")

    def _valores_que_coinciden(self, col: Columna, valores) -> frozenset:
        claves = {_clave_igualdad(v) for v in valores}
        return frozenset(v for v in self._distintos(col.tabla, col.columna) if _clave_igualdad(v) in claves)

    def _arbol(self, medida: str):
        if medida not in self._arboles:
            if medida not in self.modelo.medidas:
                raise ErrorDAX(f"La medida [{medida}] no existe en el modelo")
            self._arboles[medida] = parsear(self.modelo.medidas[medida].expresion)
        return self._arboles[medida]

    def _indice_fk(self, tabla: str, columna: str) -> dict:
        clave = (tabla, columna)
        if clave not in self._indices_fk:
            serie = pd.Series(np.arange(len(self.datos[tabla])), index=self._arr(tabla, columna))
            self._indices_fk[clave] = serie.groupby(level=0).indices
            self._indices_fk[clave] = {k: serie.to_numpy()[v] for k, v in self._indices_fk[clave].items()}
        return self._indices_fk[clave]

    def _visibles(self, tabla: str, ctx: Contexto) -> np.ndarray:
        """Máscara de filas de `tabla` que pasan los filtros, propios y de sus dimensiones."""
        filtros = ctx.filtros_dict()
        clave = (tabla, ctx.filtros)
        if clave in self._cache_visibles:
            return self._cache_visibles[clave]
        df = self.datos[tabla]
        mascara = np.ones(len(df), dtype=bool)
        for (t, c), valores in filtros.items():
            if t == tabla:
                mascara &= self._mascara_columna(tabla, c, valores)
        for rel in self.modelo.relaciones:
            if not rel.activa or rel.tabla_desde != tabla:
                continue
            if not self._tiene_filtros_aguas_arriba(rel.tabla_hacia, filtros):
                continue
            vis_dim = self._visibles(rel.tabla_hacia, ctx)
            claves = self._arr(rel.tabla_hacia, rel.columna_hacia)[vis_dim]
            if len(claves) < 0.05 * len(df):
                idx = self._indice_fk(tabla, rel.columna_desde)
                sub = np.zeros(len(df), dtype=bool)
                for k in claves:
                    pos = idx.get(_normalizar(k))
                    if pos is not None:
                        sub[pos] = True
                mascara &= sub
            else:
                mascara &= df[rel.columna_desde].isin(claves).to_numpy()
        # las relaciones bidireccionales también filtran del lado uno hacia el lado muchos
        for rel in self.modelo.relaciones:
            if rel.activa and rel.bidireccional and rel.tabla_hacia == tabla:
                # el hecho se filtra sin los filtros de esta tabla, para no entrar en un ciclo
                sin_esta = {k: v for k, v in filtros.items() if k[0] != tabla}
                if self._tiene_filtros_aguas_arriba(rel.tabla_desde, sin_esta):
                    vis_hecho = self._visibles(rel.tabla_desde, Contexto().con_filtros(sin_esta))
                    claves = self._arr(rel.tabla_desde, rel.columna_desde)[vis_hecho]
                    mascara &= df[rel.columna_hacia].isin(claves).to_numpy()
        if len(self._cache_visibles) > 20000:
            self._cache_visibles.clear()
        self._cache_visibles[clave] = mascara
        return mascara

    def _arr(self, tabla: str, columna: str) -> np.ndarray:
        clave = (tabla, columna)
        if clave not in self._cache_arreglos:
            self._cache_arreglos[clave] = self.datos[tabla][columna].to_numpy(dtype=object) \
                if self.datos[tabla][columna].dtype.kind not in "biuf" else self.datos[tabla][columna].to_numpy()
        return self._cache_arreglos[clave]

    def _distintos(self, tabla: str, columna: str) -> list:
        clave = (tabla, columna)
        if clave not in self._cache_distintos:
            self._cache_distintos[clave] = [_normalizar(v) for v in pd.unique(self._arr(tabla, columna))]
        return self._cache_distintos[clave]

    def _mascara_columna(self, tabla: str, columna: str, valores: frozenset) -> np.ndarray:
        clave = (tabla, columna, valores)
        if clave not in self._cache_columnas:
            if len(valores) <= 3 and self.datos[tabla][columna].nunique() > 1000:
                idx = self._indice_fk(tabla, columna)
                m = np.zeros(len(self.datos[tabla]), dtype=bool)
                for v in valores:
                    if v in idx:
                        m[idx[v]] = True
            else:
                m = self.datos[tabla][columna].isin(list(valores)).to_numpy()
            if len(self._cache_columnas) > 50000:
                self._cache_columnas.clear()
            self._cache_columnas[clave] = m
        return self._cache_columnas[clave]

    def _tiene_filtros_aguas_arriba(self, tabla: str, filtros: dict, vistos=None) -> bool:
        vistos = vistos or set()
        if tabla in vistos:
            return False
        vistos.add(tabla)
        if any(t == tabla for t, _ in filtros):
            return True
        return any(self._tiene_filtros_aguas_arriba(r.tabla_hacia, filtros, vistos)
                   for r in self.modelo.relaciones if r.activa and r.tabla_desde == tabla)

    # ---------------------------------------------------------- evaluación

    def _medida(self, nombre: str, ctx: Contexto):
        ctx = self._transicion(ctx)
        return self._eval(self._arbol(nombre), Contexto(ctx.filtros))

    def _transicion(self, ctx: Contexto) -> Contexto:
        """Convierte las filas en iteración en filtros por la clave de su tabla."""
        if not ctx.filas:
            return ctx
        filtros = ctx.filtros_dict()
        for tabla, i in ctx.filas:
            clave = self.modelo.tablas[tabla].clave()
            if clave is None:
                raise ErrorDAX(f"No puedo hacer transición de contexto en {tabla}: no tiene columna clave")
            filtros[(tabla, clave)] = frozenset([_normalizar(self._arr(tabla, clave)[i])])
        return Contexto(variables=ctx.variables).con_filtros(filtros).sin_filas()

    def _eval(self, n, ctx: Contexto):
        if isinstance(n, Numero):
            return int(n.valor) if n.valor.is_integer() else n.valor
        if isinstance(n, Texto):
            return n.valor
        if isinstance(n, Logico):
            return n.valor
        if isinstance(n, Variable):
            for nombre, valor in reversed(ctx.variables):
                if nombre == n.nombre:
                    return valor
            raise ErrorDAX(f"Variable {n.nombre} sin definir")
        if isinstance(n, Medida):
            return self._medida(n.nombre, ctx)
        if isinstance(n, Columna):
            return self._valor_columna(n, ctx)
        if isinstance(n, Bloque):
            for nombre, expr in n.variables:
                ctx = ctx.con_variable(nombre, self._eval(expr, ctx))
            return self._eval(n.retorno, ctx)
        if isinstance(n, Unaria):
            v = self._eval(n.valor, ctx)
            if v is BLANK:
                return BLANK
            return -v if n.op == "-" else v
        if isinstance(n, Binaria):
            return self._binaria(n, ctx)
        if isinstance(n, En):
            v = _clave_igualdad(self._eval(n.valor, ctx))
            return any(v == _clave_igualdad(self._eval(o, ctx)) for o in n.opciones)
        if isinstance(n, Funcion):
            return self._funcion(n, ctx)
        if isinstance(n, Tabla):
            raise ErrorDAX(f"La tabla {n.nombre} se usó donde se esperaba un valor")
        raise ErrorDAX(f"No sé evaluar {n!r}")

    def _valor_columna(self, col: Columna, ctx: Contexto):
        self._validar_columna(col)
        for tabla, i in ctx.filas:
            if tabla == col.tabla:
                return _normalizar(self._arr(tabla, col.columna)[i])
            if tabla == "__valor__" and i[0] == (col.tabla, col.columna):
                return i[1]
        raise ErrorDAX(f"{col} se usó sin agregación y fuera de un contexto de fila")

    def _binaria(self, n: Binaria, ctx: Contexto):
        op = n.op
        if op in ("&&", "||"):
            a = bool(self._eval(n.izq, ctx))
            if op == "&&" and not a:
                return False
            if op == "||" and a:
                return True
            return bool(self._eval(n.der, ctx))
        a, b = self._eval(n.izq, ctx), self._eval(n.der, ctx)
        if op == "&":
            return f"{'' if a is BLANK else a}{'' if b is BLANK else b}"
        if op in ("=", "<>", "<", ">", "<=", ">="):
            if a is BLANK and b is BLANK:
                return op in ("=", "<=", ">=")
            if a is BLANK:
                a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0)
            if b is BLANK:
                b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0)
            a, b = _clave_igualdad(a), _clave_igualdad(b)
            return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        if op in ("+", "-"):
            if a is BLANK and b is BLANK:
                return BLANK
            a, b = a or 0, b or 0
            return a + b if op == "+" else a - b
        if op in ("*", "^"):
            if a is BLANK or b is BLANK:
                return BLANK
            return a * b if op == "*" else a ** b
        if op == "/":
            if a is BLANK:
                return BLANK
            if b is BLANK or b == 0:
                return math.nan if a == 0 else math.copysign(math.inf, a)
            return a / b
        raise ErrorDAX(f"Operador {op} no soportado")

    # ---------------------------------------------------------- tablas

    def _tabla(self, n, ctx: Contexto) -> _Filas:
        if isinstance(n, Tabla):
            if n.nombre not in self.datos:
                raise ErrorDAX(f"La tabla {n.nombre} no existe en el modelo")
            return _Filas(n.nombre, np.flatnonzero(self._visibles(n.nombre, self._transicion(ctx))))
        if isinstance(n, Funcion) and n.nombre == "FILTER":
            base = self._tabla(n.args[0], ctx)
            quedan = [i for i in base.indices if self._eval(n.args[1], ctx.con_fila(base.tabla, int(i)))]
            return _Filas(base.tabla, np.array(quedan, dtype=int))
        if isinstance(n, Funcion) and n.nombre in ("ALL", "REMOVEFILTERS") and isinstance(n.args[0], Tabla):
            return _Filas(n.args[0].nombre, np.arange(len(self.datos[n.args[0].nombre])))
        raise ErrorDAX(f"No sé usar {n!r} como tabla")

    # ---------------------------------------------------------- funciones

    def _agregado(self, nombre: str, col: Columna, ctx: Contexto):
        self._validar_columna(col)
        vis = self._visibles(col.tabla, self._transicion(ctx))
        valores = self._arr(col.tabla, col.columna)[vis]
        if len(valores) == 0:
            return BLANK
        if nombre == "SUM":
            return _normalizar(valores.sum())
        if nombre == "DISTINCTCOUNT":
            return int(len(pd.unique(valores)))
        if nombre == "AVERAGE":
            return float(valores.mean())
        if nombre == "MIN":
            return _normalizar(valores.min())
        if nombre == "MAX":
            return _normalizar(valores.max())
        if nombre == "SELECTEDVALUE":
            unicos = pd.unique(valores)
            return _normalizar(unicos[0]) if len(unicos) == 1 else BLANK
        raise ErrorDAX(nombre)

    def _funcion(self, f: Funcion, ctx: Contexto):
        nombre, args = f.nombre, f.args
        if nombre in ("SUM", "DISTINCTCOUNT", "AVERAGE", "MIN", "MAX") and len(args) == 1:
            if not isinstance(args[0], Columna):
                raise ErrorDAX(f"{nombre} espera una columna")
            return self._agregado(nombre, args[0], ctx)
        if nombre == "SELECTEDVALUE":
            v = self._agregado("SELECTEDVALUE", args[0], ctx)
            return v if v is not BLANK or len(args) == 1 else self._eval(args[1], ctx)
        if nombre == "COUNTROWS":
            filas = self._tabla(args[0], ctx)
            return int(len(filas.indices)) or BLANK
        if nombre in ("SUMX", "AVERAGEX"):
            filas = self._tabla(args[0], ctx)
            vals = [self._eval(args[1], ctx.con_fila(filas.tabla, int(i))) for i in filas.indices]
            vals = [v for v in vals if v is not BLANK]
            if not vals:
                return BLANK
            return sum(vals) if nombre == "SUMX" else sum(vals) / len(vals)
        if nombre == "DIVIDE":
            a, b = self._eval(args[0], ctx), self._eval(args[1], ctx)
            alterno = self._eval(args[2], ctx) if len(args) > 2 else BLANK
            if b is BLANK or b == 0:
                return alterno
            if a is BLANK:
                return BLANK
            return a / b
        if nombre == "CALCULATE":
            return self._calculate(args, ctx)
        if nombre == "IF":
            cond = self._eval(args[0], ctx)
            if cond is not BLANK and cond:
                return self._eval(args[1], ctx)
            return self._eval(args[2], ctx) if len(args) > 2 else BLANK
        if nombre == "NOT":
            return not bool(self._eval(args[0], ctx))
        if nombre == "ISBLANK":
            return self._eval(args[0], ctx) is BLANK
        if nombre == "BLANK":
            return BLANK
        if nombre in ("TRUE", "FALSE"):
            return nombre == "TRUE"
        if nombre == "COALESCE":
            for a in args:
                v = self._eval(a, ctx)
                if v is not BLANK:
                    return v
            return BLANK
        if nombre in ("AND", "OR"):
            a, b = bool(self._eval(args[0], ctx)), bool(self._eval(args[1], ctx))
            return (a and b) if nombre == "AND" else (a or b)
        raise ErrorDAX(f"La función {nombre} no está soportada por el motor local")

    def _calculate(self, args, ctx: Contexto):
        ctx = self._transicion(ctx)
        filtros = ctx.filtros_dict()
        quitar, poner, mantener = [], {}, {}
        for a in args[1:]:
            if isinstance(a, Funcion) and a.nombre in ("ALL", "REMOVEFILTERS"):
                for x in a.args:
                    if isinstance(x, Tabla):
                        if x.nombre not in self.modelo.tablas:
                            raise ErrorDAX(f"La tabla {x.nombre} no existe en el modelo")
                        quitar.extend((x.nombre, c) for c in self.modelo.tablas[x.nombre].columnas)
                    elif isinstance(x, Columna):
                        self._validar_columna(x)
                        quitar.append((x.tabla, x.columna))
                    else:
                        raise ErrorDAX(f"{a.nombre} espera tablas o columnas")
            elif isinstance(a, Funcion) and a.nombre == "KEEPFILTERS":
                col, valores = self._filtro_booleano(a.args[0], ctx)
                mantener[(col.tabla, col.columna)] = valores
            else:
                col, valores = self._filtro_booleano(a, ctx)
                poner[(col.tabla, col.columna)] = valores
        for k in quitar:
            filtros.pop(k, None)
        filtros.update(poner)
        for k, v in mantener.items():
            filtros[k] = filtros[k] & v if k in filtros else v
        return self._eval(args[0], Contexto(variables=ctx.variables).con_filtros(filtros))

    def _filtro_booleano(self, expr, ctx: Contexto) -> tuple[Columna, frozenset]:
        """`T[c] = valor` como CALCULATE lo entiende: FILTER(ALL(T[c]), predicado)."""
        from .dax import referencias
        cols, meds, _ = referencias(expr)
        if len(cols) != 1 or meds:
            raise ErrorDAX("Un filtro booleano de CALCULATE debe usar una sola columna y ninguna medida")
        col = next(iter(cols))
        self._validar_columna(col)
        clave = (expr, ctx.variables)
        if clave not in self._cache_booleanos:
            valores = []
            for v in self._distintos(col.tabla, col.columna):
                c2 = Contexto(ctx.filtros, (("__valor__", ((col.tabla, col.columna), v)),), ctx.variables)
                if self._eval(expr, c2):
                    valores.append(v)
            self._cache_booleanos[clave] = frozenset(valores)
        return col, self._cache_booleanos[clave]
