"""
Las medidas de los tres reportes que existían antes del modelo único.

Cada área tenía su propio .pbix con su copia de las tablas y sus medidas. Las
medidas de cada reporte están en legado/*.tmdl tal como estaban escritas; aquí
se evalúan contra los mismos datos que el modelo para mostrar cuánto difieren
y se les pasan las mismas reglas.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from .motor import Motor
from .reglas import Hallazgo, revisar_medidas
from .tmdl import MedidaModelo, Modelo, TablaModelo, leer_objetos

REPORTES = {
    "registros_academicos": "Registros Académicos",
    "finanzas": "Finanzas",
    "direccion_academica": "Dirección Académica",
}
MODELO_UNICO = "Modelo único"

# indicador -> [(reporte, medida)]; el modelo único va al final
COMPARACIONES = {
    "Alumnos matriculados": [("Registros Académicos", "Matriculados"), ("Finanzas", "Matriculados"),
                             ("Dirección Académica", "Total alumnos"), (MODELO_UNICO, "Alumnos matriculados")],
    "Ingresantes": [("Registros Académicos", "Ingresantes"), (MODELO_UNICO, "Ingresantes")],
    "Ocupación de secciones": [("Registros Académicos", "Ocupacion"), ("Dirección Académica", "Ocupación"),
                               (MODELO_UNICO, "Ocupación %")],
    "Secciones para revisar cierre": [("Dirección Académica", "Secciones a cerrar"),
                                      (MODELO_UNICO, "Secciones bajo 40%")],
}


@dataclass
class FilaComparacion:
    indicador: str
    reporte: str
    medida: str
    valor: float | None


def cargar_legado(carpeta: str | Path) -> dict[str, list[MedidaModelo]]:
    """{reporte: [medidas]} leído de legado/*.tmdl."""
    salida = {}
    for f in sorted(Path(carpeta).glob("*.tmdl")):
        reporte = REPORTES.get(f.stem, f.stem)
        medidas = []
        for obj in leer_objetos(f.read_text(encoding="utf-8"), f.name):
            for h in obj.hijos:
                if h.tipo == "measure":
                    medidas.append(MedidaModelo(
                        tabla=f"{reporte}", nombre=h.nombre, expresion=(h.valor or "").strip(),
                        descripcion=h.descripcion, formato=h.propiedades.get("formatString", ""),
                        carpeta=h.propiedades.get("displayFolder", ""), archivo=f.name))
        salida[reporte] = medidas
    return salida


def _nombre_interno(reporte: str, medida: str) -> str:
    return f"{reporte} / {medida}"


def modelo_con_legado(modelo: Modelo, legado: dict[str, list[MedidaModelo]]) -> Modelo:
    """Copia del modelo con las medidas de cada reporte en su propia tabla.

    Las referencias [Medida] dentro de un reporte apuntan a medidas del mismo
    reporte, así que se renombran con el prefijo del reporte.
    """
    m = copy.deepcopy(modelo)
    for reporte, medidas in legado.items():
        tabla = TablaModelo(f"__{reporte}")
        nombres = {x.nombre for x in medidas}
        for x in medidas:
            expr = x.expresion
            for n in sorted(nombres, key=len, reverse=True):
                expr = expr.replace(f"[{n}]", f"[{_nombre_interno(reporte, n)}]")
            nueva = copy.copy(x)
            nueva.nombre, nueva.expresion = _nombre_interno(reporte, x.nombre), expr
            tabla.medidas[nueva.nombre] = nueva
        m.tablas[tabla.nombre] = tabla
    return m


def comparar(motor: Motor, legado: dict[str, list[MedidaModelo]], filtros: dict) -> list[FilaComparacion]:
    """Valor de cada versión de los indicadores con los mismos filtros."""
    motor_leg = Motor(modelo_con_legado(motor.modelo, legado), motor.datos)
    filas = []
    for indicador, versiones in COMPARACIONES.items():
        for reporte, medida in versiones:
            nombre = medida if reporte == MODELO_UNICO else _nombre_interno(reporte, medida)
            r = motor_leg.evaluar(nombre, filtros)
            filas.append(FilaComparacion(indicador, reporte, medida, r.get(None)))
    return filas


def revisar_legado(modelo: Modelo, legado: dict[str, list[MedidaModelo]]) -> dict[str, list[Hallazgo]]:
    """Las reglas de medidas aplicadas a cada reporte."""
    salida = {}
    for reporte, medidas in legado.items():
        m = modelo_con_legado(modelo, {reporte: medidas})
        propias = list(m.tablas[f"__{reporte}"].medidas.values())
        hallazgos = revisar_medidas(m, propias)
        for h in hallazgos:
            h.objeto = h.objeto.replace(f"{reporte} / ", "")
        salida[reporte] = hallazgos
    return salida
