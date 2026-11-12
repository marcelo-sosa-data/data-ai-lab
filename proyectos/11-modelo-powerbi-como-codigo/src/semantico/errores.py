"""
Errores sembrados: la prueba de que los controles del CI atrapan lo que deben.

Cada error es un cambio chico y plausible sobre el TMDL, de los que se cometen
editando un modelo a mano o en Desktop. Se aplica en una copia temporal del
modelo y se corren los mismos controles que corren en cada pull request:
lectura del TMDL, reglas y pruebas de medidas. Un error queda atrapado si
algún control con severidad de error falla.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .dax import ErrorDAX
from .motor import Motor
from .pruebas import Caso, correr
from .reglas import hay_errores, revisar
from .tmdl import ErrorTMDL, cargar_modelo


@dataclass(frozen=True)
class Error:
    id: str
    descripcion: str
    archivo: str          # relativo a definition/
    buscar: str
    reemplazar: str


T = "\t"
ERRORES = [
    Error("E01", "Alumnos matriculados vuelve a contar a quien se retiró de todos sus cursos",
          "tables/Matricula.tmdl",
          f"DISTINCTCOUNT ( Matricula[id_alumno] ),\n{T*4}Matricula[retiro_total] = FALSE ()",
          "DISTINCTCOUNT ( Matricula[id_alumno] )"),
    Error("E02", "COUNTROWS en vez de DISTINCTCOUNT en Alumnos matriculados",
          "tables/Matricula.tmdl",
          f"DISTINCTCOUNT ( Matricula[id_alumno] ),\n{T*4}Matricula[retiro_total] = FALSE ()",
          f"COUNTROWS ( Matricula ),\n{T*4}Matricula[retiro_total] = FALSE ()"),
    Error("E03", "Año anterior con orden - 1 (compara contra el semestre anterior)",
          "tables/Matricula.tmdl",
          "CALCULATE ( [Alumnos matriculados], REMOVEFILTERS ( Periodo ), Periodo[orden] = orden - 2 )",
          "CALCULATE ( [Alumnos matriculados], REMOVEFILTERS ( Periodo ), Periodo[orden] = orden - 1 )"),
    Error("E04", "Variación con el orden de la resta invertido",
          "tables/Matricula.tmdl",
          "DIVIDE ( [Alumnos matriculados] - [Matriculados año anterior], [Matriculados año anterior] )",
          "DIVIDE ( [Matriculados año anterior] - [Alumnos matriculados], [Matriculados año anterior] )"),
    Error("E05", "Participación de sede sin REMOVEFILTERS (siempre da 100%)",
          "tables/Matricula.tmdl",
          "DIVIDE ( [Alumnos matriculados], CALCULATE ( [Alumnos matriculados], REMOVEFILTERS ( Sede ) ) )",
          "DIVIDE ( [Alumnos matriculados], CALCULATE ( [Alumnos matriculados] ) )"),
    Error("E06", "Participación que quita todos los filtros, también el de carrera",
          "tables/Matricula.tmdl",
          "CALCULATE ( [Alumnos matriculados], REMOVEFILTERS ( Sede ) ) )",
          "CALCULATE ( [Alumnos matriculados], REMOVEFILTERS ( Sede ), REMOVEFILTERS ( Carrera ) ) )"),
    Error("E07", "Ingresantes incluye a los reincorporados",
          "tables/Matricula.tmdl",
          'Matricula[tipo_alumno] = "Ingresante" )',
          'Matricula[tipo_alumno] IN { "Ingresante", "Reincorporado" } )'),
    Error("E08", "Retiros totales copiado de otra medida con FALSE",
          "tables/Matricula.tmdl",
          f"DISTINCTCOUNT ( Matricula[id_alumno] ),\n{T*4}Matricula[retiro_total] = TRUE ()",
          f"DISTINCTCOUNT ( Matricula[id_alumno] ),\n{T*4}Matricula[retiro_total] = FALSE ()"),
    Error("E09", "Créditos promedio dividido entre todas las filas, con retiros",
          "tables/Matricula.tmdl",
          "DIVIDE ( SUM ( Matricula[creditos_vigentes] ), [Alumnos matriculados] )",
          "DIVIDE ( SUM ( Matricula[creditos_vigentes] ), COUNTROWS ( Matricula ) )"),
    Error("E10", "Alumnos regulares apunta a una columna que se renombró",
          "tables/Matricula.tmdl",
          "Matricula[creditos_vigentes] >= 12",
          "Matricula[creditos] >= 12"),
    Error("E11", "Ocupación con todas las inscripciones, también las retiradas",
          "tables/Seccion.tmdl",
          "DIVIDE ( [Inscripciones vigentes], [Vacantes] )",
          "DIVIDE ( COUNTROWS ( Inscripcion ), [Vacantes] )"),
    Error("E12", "Ocupación con / en vez de DIVIDE",
          "tables/Seccion.tmdl",
          "DIVIDE ( [Inscripciones vigentes], [Vacantes] )",
          "[Inscripciones vigentes] / [Vacantes]"),
    Error("E13", "Umbral de secciones escrito como 40 en vez de 0.4",
          "tables/Seccion.tmdl",
          "[Ocupación %] < 0.4",
          "[Ocupación %] < 40"),
    Error("E14", "La columna de origen cambió de nombre en el pipeline",
          "tables/Matricula.tmdl",
          "sourceColumn: tipo_alumno",
          "sourceColumn: tipo"),
    Error("E15", "Relación Matricula-Alumno puesta en bidireccional",
          "relationships.tmdl",
          "fromColumn: Matricula.id_alumno\n\ttoColumn: Alumno.id_alumno",
          "fromColumn: Matricula.id_alumno\n\ttoColumn: Alumno.id_alumno\n\tcrossFilteringBehavior: bothDirections"),
    Error("E16", "Relación Curso-Carrera desactivada",
          "relationships.tmdl",
          "\tfromColumn: Curso.id_carrera\n\ttoColumn: Carrera.id_carrera\n",
          "\tfromColumn: Curso.id_carrera\n\ttoColumn: Carrera.id_carrera\n\tisActive: false\n"),
    Error("E17", "Partición de Inscripcion con la ruta de producción escrita a mano",
          "tables/Inscripcion.tmdl",
          'RutaDatos & "/inscripcion.parquet"',
          '"https://mirasoldatos.dfs.core.windows.net/matricula-prod/inscripcion.parquet"'),
    Error("E18", "Medida nueva sin descripción ni prueba",
          "tables/Matricula.tmdl",
          "\tcolumn id_alumno\n",
          "\tmeasure 'Alumnos con deuda' = CALCULATE ( [Alumnos matriculados], "
          "Matricula[pago_primera_cuota] = FALSE () )\n\t\tformatString: #,0\n\t\tdisplayFolder: Pagos\n\n"
          "\tcolumn id_alumno\n"),
    Error("E19", "% pagó primera cuota con formato de número",
          "tables/Matricula.tmdl",
          "\t\tformatString: 0.0%\n\t\tdisplayFolder: Pagos",
          "\t\tformatString: 0.00\n\t\tdisplayFolder: Pagos"),
]


@dataclass
class ResultadoError:
    error: Error
    lectura: str = ""                         # error al leer el TMDL, si hubo
    reglas: list = field(default_factory=list)  # ids de reglas con severidad error
    avisos: list = field(default_factory=list)
    pruebas_fallidas: list = field(default_factory=list)

    @property
    def atrapado(self) -> bool:
        return bool(self.lectura or self.reglas or self.pruebas_fallidas)

    @property
    def controles(self) -> list[str]:
        c = []
        if self.lectura:
            c.append("lectura")
        if self.reglas:
            c.append("reglas")
        if self.pruebas_fallidas:
            c.append("pruebas")
        return c


def aplicar(carpeta_modelo: Path, error: Error, destino: Path) -> Path:
    """Copia el modelo a `destino` con el error aplicado y devuelve la copia."""
    copia = destino / carpeta_modelo.name
    shutil.copytree(carpeta_modelo, copia)
    archivo = copia / "definition" / error.archivo
    texto = archivo.read_text(encoding="utf-8")
    if texto.count(error.buscar) < 1:
        raise ValueError(f"{error.id}: no encuentro el texto a reemplazar en {error.archivo}")
    archivo.write_text(texto.replace(error.buscar, error.reemplazar, 1), encoding="utf-8")
    return copia


def evaluar_error(carpeta_modelo: Path, error: Error, carpeta_datos: Path, casos: list[Caso],
                  con, datos_cache: dict | None = None) -> ResultadoError:
    res = ResultadoError(error)
    with tempfile.TemporaryDirectory() as tmp:
        copia = aplicar(Path(carpeta_modelo), error, Path(tmp))
        try:
            modelo = cargar_modelo(copia)
        except ErrorTMDL as e:
            res.lectura = str(e)
            return res
        hallazgos = revisar(modelo, {c.medida for c in casos})
        res.reglas = sorted({h.regla for h in hallazgos if h.severidad == "error"})
        res.avisos = sorted({h.regla for h in hallazgos if h.severidad == "aviso"})
        try:
            motor = Motor.desde_carpeta(modelo, carpeta_datos)
        except ErrorDAX as e:
            res.pruebas_fallidas = ["carga de datos: " + str(e)]
            return res
        res.pruebas_fallidas = [r.caso.id for r in correr(motor, casos, con) if not r.ok]
    return res


def evaluar_todos(carpeta_modelo: Path, carpeta_datos: Path, casos: list[Caso], con,
                  errores=ERRORES) -> list[ResultadoError]:
    return [evaluar_error(carpeta_modelo, e, carpeta_datos, casos, con) for e in errores]


__all__ = ["ERRORES", "Error", "ResultadoError", "aplicar", "evaluar_error", "evaluar_todos", "hay_errores"]
