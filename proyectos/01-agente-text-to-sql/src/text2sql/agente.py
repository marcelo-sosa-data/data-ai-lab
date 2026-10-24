"""Loop del agente: el modelo pide herramientas, se ejecutan y se le devuelve el resultado."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .db import BaseDatos
from .herramientas import DEFINICIONES, ejecutar_herramienta
from .llm import Modelo
from .prompts import armar_sistema


@dataclass
class Paso:
    herramienta: str
    entrada: dict
    salida: str
    error: bool
    pensamiento: str = ""


@dataclass
class Resultado:
    pregunta: str
    respuesta: str = ""
    sql: str = ""
    columnas: list[str] = field(default_factory=list)
    filas: list[tuple] = field(default_factory=list)
    pasos: list[Paso] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos: float = 0.0
    ok: bool = False

    @property
    def consultas_fallidas(self) -> int:
        return sum(1 for p in self.pasos if p.herramienta == "ejecutar_sql" and p.error)


class AgenteTextToSQL:
    def __init__(self, modelo: Modelo, db: BaseDatos, max_pasos: int = 10):
        self.modelo = modelo
        self.db = db
        self.max_pasos = max_pasos
        self.sistema = armar_sistema(*db.rango_fechas())

    def preguntar(self, pregunta: str) -> Resultado:
        inicio = time.perf_counter()
        res = Resultado(pregunta=pregunta)
        mensajes: list[dict] = [{"role": "user", "content": pregunta}]
        ultimo_sql_ok = ""

        for _ in range(self.max_pasos):
            r = self.modelo.completar(self.sistema, mensajes, DEFINICIONES)
            res.tokens_entrada += r.tokens_entrada
            res.tokens_salida += r.tokens_salida
            mensajes.append(r.como_mensaje())

            if not r.herramientas:
                # El modelo contestó en texto sin usar `responder`: se acepta
                # y se toma como sustento la última consulta que funcionó.
                res.respuesta = r.texto.strip()
                res.sql = ultimo_sql_ok
                break

            final = next((h for h in r.herramientas if h.nombre == "responder"), None)
            if final:
                res.respuesta = final.entrada.get("respuesta", "").strip()
                res.sql = final.entrada.get("sql", "").strip() or ultimo_sql_ok
                break

            # cada tool_call recibe su propio mensaje `tool`; los errores van en el
            # contenido ("ERROR: ...") para que el modelo los lea y corrija
            for h in r.herramientas:
                salida, error = ejecutar_herramienta(self.db, h.nombre, h.entrada)
                res.pasos.append(Paso(h.nombre, h.entrada, salida, error, r.texto.strip()))
                if h.nombre == "ejecutar_sql" and not error:
                    ultimo_sql_ok = h.entrada["sql"]
                mensajes.append({"role": "tool", "tool_call_id": h.id, "content": salida})
        else:
            res.respuesta = ("No llegué a una respuesta dentro del límite de pasos. "
                             "Prueba reformulando la pregunta con más detalle.")
            res.sql = ultimo_sql_ok

        # Se vuelve a correr el SQL final para entregar la tabla completa
        if res.sql:
            consulta = self.db.ejecutar(res.sql)
            if consulta.ok:
                res.sql, res.columnas, res.filas = consulta.sql, consulta.columnas, consulta.filas
                res.ok = bool(res.respuesta)

        res.segundos = time.perf_counter() - inicio
        return res
