"""
Pruebas de datos. Cada archivo de pruebas/ es una consulta que devuelve las
filas que incumplen la regla; cero filas es una prueba aprobada. El
encabezado dice la severidad: un error bloquea la publicación, un aviso no.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

RAIZ = Path(__file__).parents[2]
CARPETA_PRUEBAS = RAIZ / "pruebas"


@dataclass
class Prueba:
    nombre: str
    severidad: str
    descripcion: str
    sql: str


@dataclass
class Resultado:
    nombre: str
    severidad: str
    descripcion: str
    filas: int
    muestra: list[dict] = field(default_factory=list)
    error_sql: str | None = None

    @property
    def aprobada(self) -> bool:
        return self.filas == 0 and self.error_sql is None

    @property
    def bloquea(self) -> bool:
        return not self.aprobada and self.severidad == "error"


def cargar(carpeta: Path = CARPETA_PRUEBAS) -> list[Prueba]:
    pruebas = []
    for ruta in sorted(Path(carpeta).glob("*.sql")):
        texto = ruta.read_text(encoding="utf-8")
        sev = re.search(r"--\s*severidad:\s*(\w+)", texto)
        desc = re.search(r"--\s*descripcion:\s*(.+)", texto)
        if not sev or sev.group(1) not in ("error", "aviso") or not desc:
            raise ValueError(f"{ruta.name}: falta '-- severidad: error|aviso' o '-- descripcion:'")
        pruebas.append(Prueba(ruta.stem, sev.group(1), desc.group(1).strip(), texto))
    return pruebas


def correr(con: duckdb.DuckDBPyConnection, pruebas: list[Prueba] | None = None) -> list[Resultado]:
    resultados = []
    for p in pruebas or cargar():
        try:
            df = con.sql(p.sql).df()
        except duckdb.Error as e:
            # una prueba que no corre cuenta como fallida: no se publica a ciegas
            resultados.append(Resultado(p.nombre, p.severidad, p.descripcion, 1, error_sql=str(e).splitlines()[0]))
            continue
        muestra = df.head(5).astype(str).to_dict("records")
        resultados.append(Resultado(p.nombre, p.severidad, p.descripcion, len(df), muestra))
    return resultados


def hay_bloqueo(resultados: list[Resultado]) -> bool:
    return any(r.bloquea for r in resultados)
