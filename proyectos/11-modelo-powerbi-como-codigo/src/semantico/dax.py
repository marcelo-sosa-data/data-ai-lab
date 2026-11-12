"""
Parser de DAX para el subconjunto que usa el modelo.

Convierte el texto de una medida en un árbol (nodos de abajo) que usan el
motor local para evaluarla y las reglas para revisar referencias y patrones.
Cubre literales, referencias a columnas y medidas, VAR/RETURN, operadores
aritméticos, de comparación y lógicos, IN { ... } y llamadas a funciones.
Una función que el parser no conoce se acepta igual; el que se queja es el motor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ErrorDAX(Exception):
    """Error de sintaxis o de evaluación en una expresión DAX."""


# ------------------------------------------------------------------ nodos

@dataclass(frozen=True)
class Numero:
    valor: float


@dataclass(frozen=True)
class Texto:
    valor: str


@dataclass(frozen=True)
class Logico:
    valor: bool


@dataclass(frozen=True)
class Columna:
    tabla: str
    columna: str

    def __str__(self) -> str:
        return f"{self.tabla}[{self.columna}]"


@dataclass(frozen=True)
class Medida:
    nombre: str


@dataclass(frozen=True)
class Tabla:
    nombre: str


@dataclass(frozen=True)
class Variable:
    nombre: str


@dataclass(frozen=True)
class Funcion:
    nombre: str
    args: tuple


@dataclass(frozen=True)
class Binaria:
    op: str
    izq: object
    der: object


@dataclass(frozen=True)
class Unaria:
    op: str
    valor: object


@dataclass(frozen=True)
class En:
    valor: object
    opciones: tuple


@dataclass(frozen=True)
class Bloque:
    variables: tuple  # ((nombre, expr), ...)
    retorno: object


# ------------------------------------------------------------------ léxico

_TOKENS = re.compile(r"""
    (?P<espacio>\s+|//[^\n]*|--[^\n]*|/\*.*?\*/)
  | (?P<columna>(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)?\[[^\]]+\])
  | (?P<tabla_q>'(?:[^']|'')+')
  | (?P<numero>\d+(?:\.\d+)?)
  | (?P<texto>"(?:[^"]|"")*")
  | (?P<op>&&|\|\||<>|<=|>=|==|[-+*/=<>(),{}&^])
  | (?P<nombre>[A-Za-z_][\w.]*)
""", re.VERBOSE | re.DOTALL)


@dataclass
class _Token:
    tipo: str
    valor: str
    pos: int


def tokenizar(texto: str) -> list[_Token]:
    pos, salida = 0, []
    while pos < len(texto):
        m = _TOKENS.match(texto, pos)
        if not m:
            raise ErrorDAX(f"Carácter inesperado {texto[pos]!r} en la posición {pos}")
        tipo = m.lastgroup
        if tipo != "espacio":
            salida.append(_Token(tipo, m.group(), pos))
        pos = m.end()
    salida.append(_Token("fin", "", pos))
    return salida


def _sin_comillas(nombre: str) -> str:
    if nombre.startswith("'"):
        return nombre[1:-1].replace("''", "'")
    return nombre


# ------------------------------------------------------------------ parser

# precedencia de menor a mayor
_NIVELES = [("||",), ("&&",), ("=", "==", "<>", "<", ">", "<=", ">="), ("&",), ("+", "-"), ("*", "/"), ("^",)]


@dataclass
class _Parser:
    tokens: list[_Token]
    i: int = 0
    variables: set = field(default_factory=set)

    def ver(self) -> _Token:
        return self.tokens[self.i]

    def tomar(self, valor: str | None = None) -> _Token:
        t = self.tokens[self.i]
        if valor is not None and t.valor.upper() != valor.upper():
            raise ErrorDAX(f"Se esperaba {valor!r} y vino {t.valor!r} (posición {t.pos})")
        self.i += 1
        return t

    def expresion(self):
        t = self.ver()
        if t.tipo == "nombre" and t.valor.upper() == "VAR":
            return self.bloque()
        return self.binaria(0)

    def bloque(self):
        variables = []
        while self.ver().tipo == "nombre" and self.ver().valor.upper() == "VAR":
            self.tomar()
            nombre = self.tomar().valor
            self.tomar("=")
            expr = self.expresion()
            self.variables.add(nombre.upper())
            variables.append((nombre.upper(), expr))
        self.tomar("RETURN")
        return Bloque(tuple(variables), self.expresion())

    def binaria(self, nivel: int):
        if nivel == len(_NIVELES):
            return self.unaria()
        izq = self.binaria(nivel + 1)
        while True:
            t = self.ver()
            if t.tipo == "op" and t.valor in _NIVELES[nivel]:
                self.tomar()
                op = "=" if t.valor == "==" else t.valor
                izq = Binaria(op, izq, self.binaria(nivel + 1))
            elif nivel == 2 and t.tipo == "nombre" and t.valor.upper() == "IN":
                self.tomar()
                self.tomar("{")
                opciones = [self.expresion()]
                while self.ver().valor == ",":
                    self.tomar()
                    opciones.append(self.expresion())
                self.tomar("}")
                izq = En(izq, tuple(opciones))
            else:
                return izq

    def unaria(self):
        t = self.ver()
        if t.tipo == "op" and t.valor in "-+":
            self.tomar()
            return Unaria(t.valor, self.unaria())
        if t.tipo == "nombre" and t.valor.upper() == "NOT" and self.tokens[self.i + 1].valor != "(":
            self.tomar()
            return Funcion("NOT", (self.binaria(2),))
        return self.primaria()

    def primaria(self):
        t = self.tomar()
        if t.tipo == "numero":
            return Numero(float(t.valor))
        if t.tipo == "texto":
            return Texto(t.valor[1:-1].replace('""', '"'))
        if t.tipo == "columna":
            tabla, _, resto = t.valor.partition("[")
            if not tabla:
                return Medida(resto[:-1])
            return Columna(_sin_comillas(tabla), resto[:-1])
        if t.tipo == "tabla_q":
            return Tabla(_sin_comillas(t.valor))
        if t.valor == "(":
            e = self.expresion()
            self.tomar(")")
            return e
        if t.tipo == "nombre":
            nombre = t.valor.upper()
            if self.ver().valor == "(":
                self.tomar("(")
                args = []
                if self.ver().valor != ")":
                    args.append(self.expresion())
                    while self.ver().valor == ",":
                        self.tomar()
                        args.append(self.expresion())
                self.tomar(")")
                return Funcion(nombre, tuple(args))
            if nombre in ("TRUE", "FALSE"):
                return Logico(nombre == "TRUE")
            if nombre in self.variables:
                return Variable(nombre)
            return Tabla(t.valor)
        raise ErrorDAX(f"Token inesperado {t.valor!r} (posición {t.pos})")


def parsear(texto: str):
    """Devuelve el árbol de la expresión o lanza ErrorDAX."""
    p = _Parser(tokenizar(texto))
    arbol = p.expresion()
    if p.ver().tipo != "fin":
        t = p.ver()
        raise ErrorDAX(f"Sobra texto desde {t.valor!r} (posición {t.pos})")
    return arbol


# ------------------------------------------------------------------ recorridos

def nodos(arbol):
    """Recorre el árbol en profundidad."""
    yield arbol
    if isinstance(arbol, Funcion):
        for a in arbol.args:
            yield from nodos(a)
    elif isinstance(arbol, Binaria):
        yield from nodos(arbol.izq)
        yield from nodos(arbol.der)
    elif isinstance(arbol, Unaria):
        yield from nodos(arbol.valor)
    elif isinstance(arbol, En):
        yield from nodos(arbol.valor)
        for o in arbol.opciones:
            yield from nodos(o)
    elif isinstance(arbol, Bloque):
        for _, e in arbol.variables:
            yield from nodos(e)
        yield from nodos(arbol.retorno)


def referencias(arbol) -> tuple[set[Columna], set[str], set[str]]:
    """Columnas, medidas y tablas que usa la expresión."""
    cols, meds, tabs = set(), set(), set()
    for n in nodos(arbol):
        if isinstance(n, Columna):
            cols.add(n)
        elif isinstance(n, Medida):
            meds.add(n.nombre)
        elif isinstance(n, Tabla):
            tabs.add(n.nombre)
    return cols, meds, tabs
