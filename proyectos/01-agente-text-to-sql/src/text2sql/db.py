"""Acceso de solo lectura a la base DuckDB y lectura del esquema."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from .guard import validar_sql


@dataclass
class ResultadoConsulta:
    ok: bool
    sql: str = ""
    columnas: list[str] = field(default_factory=list)
    filas: list[tuple] = field(default_factory=list)
    truncado: bool = False
    error: str = ""


def _a_json(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


class BaseDatos:
    def __init__(self, ruta: str | Path, max_filas: int = 200, timeout_seg: float = 15.0):
        ruta = Path(ruta)
        if not ruta.exists():
            raise FileNotFoundError(
                f"No encuentro la base en {ruta}. Genérala con: python datos/generar_datos.py"
            )
        self.con = duckdb.connect(str(ruta), read_only=True)
        self.max_filas = max_filas
        self.timeout_seg = timeout_seg
        self.tablas = {
            r[0] for r in self.con.execute(
                "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
            ).fetchall()
        }

    # ------------------------------------------------------------------ esquema

    def listar_tablas(self) -> list[dict]:
        filas = self.con.execute("""
            SELECT table_name, COALESCE(comment, ''), estimated_size
            FROM duckdb_tables() WHERE schema_name = 'main' ORDER BY table_name
        """).fetchall()
        return [{"tabla": t, "descripcion": c, "filas_aprox": n} for t, c, n in filas]

    def describir_tabla(self, tabla: str) -> dict:
        tabla = tabla.strip().lower()
        if tabla not in self.tablas:
            return {"error": f"La tabla '{tabla}' no existe. Disponibles: {sorted(self.tablas)}"}

        columnas = self.con.execute("""
            SELECT column_name, data_type, COALESCE(comment, '')
            FROM duckdb_columns()
            WHERE schema_name = 'main' AND table_name = ?
            ORDER BY column_index
        """, [tabla]).fetchall()

        detalle = []
        for nombre, tipo, comentario in columnas:
            col = {"columna": nombre, "tipo": tipo}
            if comentario:
                col["descripcion"] = comentario
            # Para columnas de texto con pocos valores, se listan: así el modelo
            # sabe que es 'Yape' y no 'YAPE' ni 'yape'.
            if tipo == "VARCHAR":
                n = self.con.execute(
                    f'SELECT COUNT(DISTINCT "{nombre}") FROM "{tabla}"'
                ).fetchone()[0]
                if n <= 15:
                    valores = self.con.execute(
                        f'SELECT DISTINCT "{nombre}" FROM "{tabla}" ORDER BY 1'
                    ).fetchall()
                    col["valores"] = [v[0] for v in valores]
            detalle.append(col)

        muestra = self.con.execute(f'SELECT * FROM "{tabla}" LIMIT 3')
        nombres = [d[0] for d in muestra.description]
        ejemplos = [dict(zip(nombres, map(_a_json, f))) for f in muestra.fetchall()]
        return {"tabla": tabla, "columnas": detalle, "ejemplos": ejemplos}

    def rango_fechas(self) -> tuple[date, date]:
        return self.con.execute(
            "SELECT MIN(fecha_hora)::DATE, MAX(fecha_hora)::DATE FROM ventas"
        ).fetchone()

    # ------------------------------------------------------------------ consultas

    def ejecutar(self, sql: str) -> ResultadoConsulta:
        validacion = validar_sql(sql, self.tablas, self.max_filas)
        if not validacion.ok:
            return ResultadoConsulta(False, sql=sql, error=validacion.motivo)

        # DuckDB no tiene statement_timeout: se corta la consulta desde otro hilo
        temporizador = threading.Timer(self.timeout_seg, self.con.interrupt)
        temporizador.start()
        try:
            cursor = self.con.execute(validacion.sql)
            columnas = [d[0] for d in cursor.description]
            filas = cursor.fetchmany(self.max_filas + 1)
        except duckdb.InterruptException:
            return ResultadoConsulta(False, sql=validacion.sql,
                                     error=f"La consulta superó {self.timeout_seg:.0f} s y se canceló.")
        except duckdb.Error as e:
            return ResultadoConsulta(False, sql=validacion.sql, error=str(e).split("\n")[0])
        finally:
            temporizador.cancel()

        truncado = len(filas) > self.max_filas
        return ResultadoConsulta(True, validacion.sql, columnas,
                                 filas[: self.max_filas], truncado)

    def cerrar(self) -> None:
        self.con.close()
