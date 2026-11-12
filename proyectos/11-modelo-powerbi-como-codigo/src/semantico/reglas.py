"""
Reglas de buenas prácticas que se revisan sobre el TMDL antes de publicar.

Son las que antes se revisaban a ojo, cuando se revisaban: medidas sin
descripción ni formato, divisiones con "/", referencias rotas, relaciones
bidireccionales, rutas fijas en las particiones y medidas sin prueba.
Un hallazgo de severidad "error" bloquea el merge; un "aviso" solo se reporta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dax import Binaria, ErrorDAX, Texto, nodos, parsear, referencias
from .tmdl import Modelo, archivo_parquet


@dataclass
class Hallazgo:
    regla: str
    severidad: str  # error | aviso
    objeto: str
    detalle: str


REGLAS = {
    "R01": ("error", "Medida sin descripción"),
    "R02": ("error", "Medida sin formato"),
    "R03": ("aviso", "Medida de porcentaje sin formato de porcentaje"),
    "R04": ("error", "División con / en vez de DIVIDE"),
    "R05": ("error", "Referencia a una columna, medida o tabla que no existe"),
    "R06": ("error", "La expresión DAX no se puede leer"),
    "R07": ("error", "Relación bidireccional"),
    "R08": ("error", "Relación hacia una columna que no es clave"),
    "R09": ("error", "Partición con ruta fija en vez del parámetro RutaDatos"),
    "R10": ("aviso", "Columna de id visible para el usuario"),
    "R11": ("aviso", "Columna de id que se suma por defecto"),
    "R12": ("aviso", "Medida sin carpeta"),
    "R13": ("error", "Medida sin prueba"),
    "R14": ("error", "Periodo escrito a mano en la medida"),
}


def _h(regla: str, objeto: str, detalle: str) -> Hallazgo:
    return Hallazgo(regla, REGLAS[regla][0], objeto, detalle)


def revisar_medidas(modelo: Modelo, medidas=None, columnas_extra: bool = True) -> list[Hallazgo]:
    """Reglas sobre medidas. `medidas` permite revisar un subconjunto (p. ej. las del legado)."""
    hallazgos = []
    medidas = medidas if medidas is not None else list(modelo.medidas.values())
    nombres = set(modelo.medidas) | {m.nombre for m in medidas}
    for m in medidas:
        obj = f"[{m.nombre}]"
        if not m.descripcion.strip():
            hallazgos.append(_h("R01", obj, "Sin /// descripción: quien la use no sabe qué cuenta"))
        if not m.formato:
            hallazgos.append(_h("R02", obj, "Sin formatString"))
        elif (m.nombre.startswith("%") or m.nombre.endswith(" %") or m.nombre.startswith("Var.")) \
                and "%" not in m.formato:
            hallazgos.append(_h("R03", obj, f"formatString {m.formato!r}"))
        if not m.carpeta:
            hallazgos.append(_h("R12", obj, "Sin displayFolder"))
        try:
            arbol = parsear(m.expresion)
        except ErrorDAX as e:
            hallazgos.append(_h("R06", obj, str(e)))
            continue
        if any(isinstance(n, Binaria) and n.op == "/" for n in nodos(arbol)):
            hallazgos.append(_h("R04", obj, "Si el denominador es 0 o BLANK devuelve infinito; usar DIVIDE"))
        for n in nodos(arbol):
            if isinstance(n, Texto) and re.fullmatch(r"20\d\d-[12]", n.valor):
                hallazgos.append(_h("R14", obj, f'"{n.valor}" fijo: hay que editar la medida cada semestre'))
        cols, meds, tabs = referencias(arbol)
        for c in cols:
            if modelo.columna(c.tabla, c.columna) is None:
                hallazgos.append(_h("R05", obj, f"La columna {c} no existe"))
        for nombre in meds:
            if nombre not in nombres:
                hallazgos.append(_h("R05", obj, f"La medida [{nombre}] no existe"))
        for t in tabs:
            if t not in modelo.tablas:
                hallazgos.append(_h("R05", obj, f"La tabla {t} no existe"))
    return hallazgos


def revisar(modelo: Modelo, medidas_probadas: set[str] | None = None) -> list[Hallazgo]:
    """Todas las reglas sobre el modelo completo."""
    hallazgos = revisar_medidas(modelo)
    for r in modelo.relaciones:
        obj = f"{r.tabla_desde}.{r.columna_desde} -> {r.tabla_hacia}.{r.columna_hacia}"
        if r.bidireccional:
            hallazgos.append(_h("R07", obj, "crossFilteringBehavior: bothDirections; los filtros del hecho "
                                "pasan a la dimensión y de ahí a otros hechos"))
        destino = modelo.columna(r.tabla_hacia, r.columna_hacia)
        if destino is None or modelo.columna(r.tabla_desde, r.columna_desde) is None:
            hallazgos.append(_h("R05", obj, "La relación usa una columna que no existe"))
        elif not destino.es_clave:
            hallazgos.append(_h("R08", obj, f"{r.tabla_hacia}.{r.columna_hacia} no tiene isKey"))
    for t in modelo.tablas.values():
        m = t.particion
        if m and ("RutaDatos" not in m or re.search(r'"(?:https?://|[A-Za-z]:\\|\\\\)', m)):
            hallazgos.append(_h("R09", t.nombre, "La partición debe armar la ruta con el parámetro RutaDatos"))
        if m and archivo_parquet(m) is None:
            hallazgos.append(_h("R09", t.nombre, "La partición no lee un Parquet de la carpeta de datos"))
        for c in t.columnas.values():
            if c.nombre.startswith("id_"):
                if not c.oculta:
                    hallazgos.append(_h("R10", f"{t.nombre}[{c.nombre}]", "Debería tener isHidden"))
                if c.resumir_por not in ("none",):
                    hallazgos.append(_h("R11", f"{t.nombre}[{c.nombre}]", f"summarizeBy: {c.resumir_por}"))
    if medidas_probadas is not None:
        for nombre in sorted(set(modelo.medidas) - medidas_probadas):
            hallazgos.append(_h("R13", f"[{nombre}]", "No hay ningún caso en pruebas_dax/casos.yaml"))
    return hallazgos


def hay_errores(hallazgos: list[Hallazgo]) -> bool:
    return any(h.severidad == "error" for h in hallazgos)
