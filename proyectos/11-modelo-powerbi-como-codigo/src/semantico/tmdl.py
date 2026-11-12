"""
Lectura de un modelo semántico en formato TMDL (carpeta definition/ de un PBIP).

Lee lo que hace falta para probar y revisar el modelo: tablas, columnas,
medidas con su descripción y formato, particiones, relaciones y parámetros.
El resto de propiedades (annotations, cultures, etc.) se guarda sin interpretar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class ErrorTMDL(Exception):
    pass


@dataclass
class Objeto:
    """Un objeto TMDL genérico: `tipo nombre [= valor]` con propiedades e hijos."""
    tipo: str
    nombre: str
    valor: str | None = None
    propiedades: dict[str, str] = field(default_factory=dict)
    hijos: list["Objeto"] = field(default_factory=list)
    descripcion: str = ""
    archivo: str = ""
    linea: int = 0


@dataclass
class ColumnaModelo:
    tabla: str
    nombre: str
    tipo_dato: str
    columna_origen: str
    es_clave: bool = False
    oculta: bool = False
    resumir_por: str = "default"
    formato: str = ""


@dataclass
class MedidaModelo:
    tabla: str
    nombre: str
    expresion: str
    descripcion: str = ""
    formato: str = ""
    carpeta: str = ""
    archivo: str = ""
    linea: int = 0


@dataclass
class TablaModelo:
    nombre: str
    columnas: dict[str, ColumnaModelo] = field(default_factory=dict)
    medidas: dict[str, MedidaModelo] = field(default_factory=dict)
    particion: str = ""  # expresión M
    oculta: bool = False

    def clave(self) -> str | None:
        return next((c.nombre for c in self.columnas.values() if c.es_clave), None)


@dataclass
class Relacion:
    nombre: str
    tabla_desde: str
    columna_desde: str
    tabla_hacia: str
    columna_hacia: str
    bidireccional: bool = False
    activa: bool = True


@dataclass
class Modelo:
    tablas: dict[str, TablaModelo] = field(default_factory=dict)
    relaciones: list[Relacion] = field(default_factory=list)
    parametros: dict[str, str] = field(default_factory=dict)

    @property
    def medidas(self) -> dict[str, MedidaModelo]:
        return {m.nombre: m for t in self.tablas.values() for m in t.medidas.values()}

    def columna(self, tabla: str, columna: str) -> ColumnaModelo | None:
        t = self.tablas.get(tabla)
        return t.columnas.get(columna) if t else None


# ------------------------------------------------------------------ lectura genérica

_ENCABEZADO = re.compile(
    r"^(?P<tipo>[a-zA-Z]+)(?:\s+(?P<nombre>'(?:[^']|'')+'|[^\s=:]+))?(?:\s*=\s*(?P<valor>.*))?$")
_PROPIEDAD = re.compile(r"^(?P<clave>[A-Za-z]+)\s*:\s*(?P<valor>.*)$")
_TIPOS_OBJETO = {"model", "database", "table", "column", "measure", "partition", "relationship",
                 "expression", "hierarchy", "level", "annotation", "ref", "culture", "role",
                 "calculationGroup", "calculationItem", "perspective", "dataAccessOptions"}


def _indentacion(linea: str) -> int:
    return len(linea) - len(linea.lstrip("\t"))


def _nombre(texto: str | None) -> str:
    if not texto:
        return ""
    texto = texto.strip()
    if texto.startswith("'") and texto.endswith("'"):
        return texto[1:-1].replace("''", "'")
    return texto


def _bloque_expresion(lineas: list[str], i: int, nivel: int) -> tuple[str, int]:
    """Junta las líneas de una expresión de varias líneas (indentadas nivel+2 o más)."""
    cuerpo = []
    while i < len(lineas):
        l = lineas[i]
        if l.strip() and _indentacion(l) < nivel + 2:
            break
        cuerpo.append(l)
        i += 1
    while cuerpo and not cuerpo[-1].strip():
        cuerpo.pop()
    sangria = min((_indentacion(l) for l in cuerpo if l.strip()), default=0)
    texto = "\n".join(l[sangria:] if l.strip() else "" for l in cuerpo)
    if texto.startswith("```"):
        texto = texto.strip("`\n")
    return texto, i


def leer_objetos(texto: str, archivo: str = "") -> list[Objeto]:
    """Parsea un archivo TMDL en una lista de objetos de primer nivel."""
    lineas = texto.replace("\r\n", "\n").split("\n")
    raiz = Objeto("raiz", "")
    pila: list[tuple[int, Objeto]] = [(-1, raiz)]
    descripcion: list[str] = []
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        bruto = linea.strip()
        nivel = _indentacion(linea)
        i += 1
        if not bruto:
            continue
        if bruto.startswith("///"):
            descripcion.append(bruto[3:].strip())
            continue
        if linea[nivel:nivel + 1] == " ":
            raise ErrorTMDL(f"{archivo}:{i}: la indentación de TMDL es con tabs")
        while pila[-1][0] >= nivel:
            pila.pop()
        padre = pila[-1][1]
        if bruto.startswith("ref "):  # `ref table X` en model.tmdl: solo fija el orden
            continue
        m = _ENCABEZADO.match(bruto)
        if m and m.group("tipo") in _TIPOS_OBJETO:
            tipo, nombre, valor = m.group("tipo"), m.group("nombre"), m.group("valor")
            if valor is not None and valor.strip() == "":
                valor, i = _bloque_expresion(lineas, i, nivel)
            obj = Objeto(tipo, _nombre(nombre), valor, descripcion="\n".join(descripcion),
                         archivo=archivo, linea=i)
            descripcion = []
            padre.hijos.append(obj)
            pila.append((nivel, obj))
            continue
        descripcion = []
        p = _PROPIEDAD.match(bruto)
        if p:
            clave, valor = p.group("clave"), p.group("valor")
            padre.propiedades[clave] = valor.strip()
            continue
        m2 = re.match(r"^(?P<clave>[A-Za-z]+)\s*=\s*(?P<valor>.*)$", bruto)
        if m2:  # propiedad con expresión, p. ej. `source =`
            valor = m2.group("valor")
            if valor.strip() == "":
                valor, i = _bloque_expresion(lineas, i, nivel)
            padre.propiedades[m2.group("clave")] = valor
            continue
        if re.fullmatch(r"[A-Za-z]+", bruto):  # bandera sin valor, p. ej. `isHidden`
            padre.propiedades[bruto] = "true"
            continue
        raise ErrorTMDL(f"{archivo}:{i}: no entiendo la línea {bruto!r}")
    return raiz.hijos


# ------------------------------------------------------------------ modelo

def _es_verdad(valor: str | None) -> bool:
    return (valor or "").strip().lower() == "true"


def _tabla_desde_objeto(obj: Objeto) -> TablaModelo:
    t = TablaModelo(obj.nombre, oculta=_es_verdad(obj.propiedades.get("isHidden")))
    for h in obj.hijos:
        if h.tipo == "column":
            p = h.propiedades
            t.columnas[h.nombre] = ColumnaModelo(
                tabla=obj.nombre, nombre=h.nombre, tipo_dato=p.get("dataType", ""),
                columna_origen=p.get("sourceColumn", h.nombre), es_clave=_es_verdad(p.get("isKey")),
                oculta=_es_verdad(p.get("isHidden")), resumir_por=p.get("summarizeBy", "default"),
                formato=p.get("formatString", ""))
        elif h.tipo == "measure":
            p = h.propiedades
            t.medidas[h.nombre] = MedidaModelo(
                tabla=obj.nombre, nombre=h.nombre, expresion=(h.valor or "").strip(),
                descripcion=h.descripcion, formato=p.get("formatString", ""),
                carpeta=p.get("displayFolder", ""), archivo=h.archivo, linea=h.linea)
        elif h.tipo == "partition":
            t.particion = h.propiedades.get("source", "")
    return t


def _ref_columna(texto: str) -> tuple[str, str]:
    """`Matricula.id_periodo` o `'Tabla x'.'col y'` -> (tabla, columna)."""
    m = re.fullmatch(r"('(?:[^']|'')+'|[^.]+)\.('(?:[^']|'')+'|.+)", texto.strip())
    if not m:
        raise ErrorTMDL(f"Referencia de columna inválida: {texto!r}")
    return _nombre(m.group(1)), _nombre(m.group(2))


def cargar_modelo(carpeta: str | Path) -> Modelo:
    """Lee `<X>.SemanticModel/definition` (o la carpeta del modelo) y arma el Modelo."""
    carpeta = Path(carpeta)
    if (carpeta / "definition").is_dir():
        carpeta = carpeta / "definition"
    if not (carpeta / "model.tmdl").exists():
        raise ErrorTMDL(f"No hay model.tmdl en {carpeta}")
    archivos = sorted(carpeta.rglob("*.tmdl"))
    return modelo_desde_textos({str(a.relative_to(carpeta)): a.read_text(encoding="utf-8") for a in archivos})


def modelo_desde_textos(textos: dict[str, str]) -> Modelo:
    """Arma el Modelo desde {ruta relativa: contenido}; sirve para leer versiones de git."""
    modelo = Modelo()
    for ruta, texto in textos.items():
        for obj in leer_objetos(texto, ruta):
            if obj.tipo == "table":
                modelo.tablas[obj.nombre] = _tabla_desde_objeto(obj)
            elif obj.tipo == "relationship":
                p = obj.propiedades
                td, cd = _ref_columna(p["fromColumn"])
                th, ch = _ref_columna(p["toColumn"])
                modelo.relaciones.append(Relacion(
                    obj.nombre, td, cd, th, ch,
                    bidireccional=p.get("crossFilteringBehavior", "") == "bothDirections",
                    activa=p.get("isActive", "true").lower() != "false"))
            elif obj.tipo == "expression":
                valor = (obj.valor or "").split(" meta ")[0].strip()
                modelo.parametros[obj.nombre] = valor.strip('"')
    return modelo


def archivo_parquet(particion_m: str) -> str | None:
    """Nombre del Parquet que lee una partición M (`... & "/matricula.parquet"`)."""
    m = re.search(r'([\w-]+\.parquet)"', particion_m)
    return m.group(1) if m else None
