"""
Servidor MCP con los sistemas de Killa: reclamos, tarjetas, movimientos,
recargas y pagos, más las operaciones que un reclamo puede generar.

Las herramientas de lectura devuelven hechos con los datos personales ya
enmascarados. Las de escritura revalidan las reglas de negocio aquí mismo,
aunque el host ya haya filtrado la llamada: si alguien conecta otro cliente
al servidor, un abono sin sustento igual se rechaza.

Uso por stdio (para conectarlo a cualquier cliente MCP):
    python -m reclamos servidor
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .guardrails import enmascarar
from .regla_actual import BACKOFFICE, CONTRACARGOS, FRAUDE, OPERACIONES

SUPERVISOR = "Supervisor de reclamos"
AREAS_DERIVACION = [FRAUDE, OPERACIONES, CONTRACARGOS, BACKOFFICE, SUPERVISOR]
TOPE_ABONO = 500.0
VENTANA_DUPLICADO = timedelta(minutes=10)
MAX_MOVIMIENTOS = 40

LECTURA = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
ESCRITURA = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
DESTRUCTIVA = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)

Motivo = Literal["cargo_duplicado", "recarga_no_acreditada", "membresia_exonerada"]
Area = Literal["Prevención de fraude", "Operaciones", "Contracargos", "Backoffice de tarjetas",
               "Supervisor de reclamos"]
ResultadoReclamo = Literal["procede_abonado", "no_procede", "derivado"]


@dataclass
class Operaciones:
    """Lo que el servidor escribió. Vive en memoria para poder evaluar sin tocar la base."""

    abonos: list[dict] = field(default_factory=list)
    derivaciones: list[dict] = field(default_factory=list)
    respuestas: list[dict] = field(default_factory=list)
    bloqueos: list[dict] = field(default_factory=list)

    def del_reclamo(self, id_reclamo: int) -> dict:
        return {
            "abonos": [a for a in self.abonos if a["id_reclamo"] == id_reclamo],
            "derivaciones": [d for d in self.derivaciones if d["id_reclamo"] == id_reclamo],
            "respuesta": next((r for r in self.respuestas if r["id_reclamo"] == id_reclamo), None),
        }


def _fecha(valor) -> str:
    return valor.strftime("%Y-%m-%d %H:%M") if isinstance(valor, datetime) else str(valor)


class Sistemas:
    """Acceso de solo lectura a la base y reglas de negocio de las operaciones."""

    def __init__(self, ruta_db: Path | str):
        self.con = duckdb.connect(str(ruta_db), read_only=True)
        self.ops = Operaciones()
        self._lock = threading.Lock()

    def _q(self, sql: str, params: list) -> list[dict]:
        cur = self.con.cursor()
        try:
            r = cur.execute(sql, params)
            cols = [d[0] for d in r.description]
            return [dict(zip(cols, f)) for f in r.fetchall()]
        finally:
            cur.close()

    # ------------------------------------------------------------ lectura

    def reclamo(self, id_reclamo: int) -> dict:
        filas = self._q("SELECT id_reclamo, codigo, id_cliente, fecha_hora, canal, texto FROM reclamos "
                        "WHERE id_reclamo = ?", [id_reclamo])
        if not filas:
            raise ToolError(f"No existe el reclamo {id_reclamo}.")
        r = filas[0]
        return {**r, "fecha_hora": _fecha(r["fecha_hora"]), "texto": enmascarar(r["texto"])}

    def cliente(self, id_cliente: int) -> dict:
        filas = self._q("""
            SELECT c.id_cliente, split_part(c.nombre, ' ', 1) AS nombre, c.departamento,
                   t.id_tarjeta, right(t.numero, 4) AS tarjeta_ultimos4, t.estado, t.linea_credito,
                   t.fecha_emision, t.exonerada_hasta
            FROM clientes c JOIN tarjetas t USING (id_cliente) WHERE c.id_cliente = ?""", [id_cliente])
        if not filas:
            raise ToolError(f"No existe el cliente {id_cliente}.")
        c = filas[0]
        return {**c, "fecha_emision": str(c["fecha_emision"]),
                "membresia_exonerada_hasta": str(c.pop("exonerada_hasta")),
                "membresia_mensual": 12.90}

    def movimientos(self, id_cliente: int, desde: str, hasta: str, comercio: str = "") -> dict:
        filas = self._q("""
            SELECT m.id_movimiento, m.fecha_hora, m.comercio, m.tipo, m.canal, m.monto, m.estado
            FROM movimientos m JOIN tarjetas t USING (id_tarjeta)
            WHERE t.id_cliente = ? AND m.fecha_hora >= CAST(? AS DATE)
              AND m.fecha_hora < CAST(? AS DATE) + INTERVAL 1 DAY
              AND (? = '' OR m.comercio ILIKE '%' || ? || '%')
            ORDER BY m.fecha_hora DESC""", [id_cliente, desde, hasta, comercio, comercio])
        total = len(filas)
        filas = [{**f, "fecha_hora": _fecha(f["fecha_hora"]), "monto": float(f["monto"])}
                 for f in filas[:MAX_MOVIMIENTOS]]
        salida = {"movimientos": filas, "total": total}
        if total > MAX_MOVIMIENTOS:
            salida["nota"] = f"Se muestran los {MAX_MOVIMIENTOS} más recientes. Acota fechas o comercio."
        return salida

    def _movimiento(self, id_movimiento: int) -> dict:
        filas = self._q("""
            SELECT m.*, t.id_cliente, t.exonerada_hasta FROM movimientos m JOIN tarjetas t USING (id_tarjeta)
            WHERE m.id_movimiento = ?""", [id_movimiento])
        if not filas:
            raise ToolError(f"No existe el movimiento {id_movimiento}.")
        return filas[0]

    def revisar_cargo(self, id_movimiento: int) -> dict:
        m = self._movimiento(id_movimiento)
        hechos: dict = {
            "id_movimiento": m["id_movimiento"], "fecha_hora": _fecha(m["fecha_hora"]),
            "comercio": m["comercio"], "tipo": m["tipo"], "monto": float(m["monto"]), "estado": m["estado"],
        }
        if m["tipo"] in ("compra", "membresia"):
            iguales = self._q("""
                SELECT id_movimiento, fecha_hora, monto, estado FROM movimientos
                WHERE id_tarjeta = ? AND comercio = ? AND id_movimiento <> ?
                  AND fecha_hora BETWEEN ? AND ? ORDER BY fecha_hora""",
                [m["id_tarjeta"], m["comercio"], id_movimiento,
                 m["fecha_hora"] - timedelta(hours=48), m["fecha_hora"] + timedelta(hours=48)])
            hechos["otros_cargos_mismo_comercio_48h"] = [
                {**c, "fecha_hora": _fecha(c["fecha_hora"]), "monto": float(c["monto"]),
                 "minutos_de_diferencia": round(abs((c["fecha_hora"] - m["fecha_hora"]).total_seconds()) / 60, 1),
                 "mismo_monto": abs(float(c["monto"]) - float(m["monto"])) < 0.01}
                for c in iguales]
        if m["tipo"] == "recarga":
            r = self._q("SELECT operador, estado_operador, fecha_respuesta FROM recargas WHERE id_movimiento = ?",
                        [id_movimiento])
            if r:
                hechos["recarga"] = {"operador": r[0]["operador"], "estado_operador": r[0]["estado_operador"],
                                     "respuesta_operador": _fecha(r[0]["fecha_respuesta"])}
        if m["tipo"] == "membresia":
            hechos["membresia_exonerada_hasta"] = str(m["exonerada_hasta"])
            hechos["cargo_dentro_de_exoneracion"] = m["fecha_hora"].date() <= m["exonerada_hasta"]
        previos = [a for a in self.ops.abonos if a["id_movimiento"] == id_movimiento]
        hechos["abonos_previos"] = len(previos)
        return hechos

    def pagos(self, id_cliente: int, desde: str, hasta: str) -> dict:
        filas = self._q("""
            SELECT p.id_pago, p.fecha_hora, p.monto, p.canal_pago, p.aplicado, p.fecha_aplicacion
            FROM pagos p JOIN tarjetas t USING (id_tarjeta)
            WHERE t.id_cliente = ? AND p.fecha_hora >= CAST(? AS DATE)
              AND p.fecha_hora < CAST(? AS DATE) + INTERVAL 1 DAY
            ORDER BY p.fecha_hora DESC""", [id_cliente, desde, hasta])
        return {"pagos": [{**f, "fecha_hora": _fecha(f["fecha_hora"]), "monto": float(f["monto"]),
                           "fecha_aplicacion": _fecha(f["fecha_aplicacion"]) if f["fecha_aplicacion"] else None}
                          for f in filas]}

    # ------------------------------------------------------------ escritura

    def _cerrado(self, id_reclamo: int) -> bool:
        return any(r["id_reclamo"] == id_reclamo for r in self.ops.respuestas)

    def emitir_abono(self, id_reclamo: int, id_movimiento: int, monto: float, motivo: str) -> dict:
        rec = self.reclamo(id_reclamo)
        m = self._movimiento(id_movimiento)
        with self._lock:
            if self._cerrado(id_reclamo):
                raise ToolError("El reclamo ya está cerrado.")
            if m["id_cliente"] != rec["id_cliente"]:
                raise ToolError("El movimiento no pertenece al cliente del reclamo.")
            if any(a["id_movimiento"] == id_movimiento for a in self.ops.abonos):
                raise ToolError("Ese movimiento ya tiene un abono. No se abona dos veces.")
            if abs(float(monto) - float(m["monto"])) > 0.01:
                raise ToolError(f"El monto del abono debe ser el del movimiento: S/ {float(m['monto']):.2f}.")
            if m["estado"] != "liquidado":
                raise ToolError(f"El movimiento está {m['estado']}; no hay nada que abonar.")
            self._validar_motivo(m, motivo)
            if float(monto) > TOPE_ABONO:
                raise ToolError(f"Abonos sobre S/ {TOPE_ABONO:.0f} requieren aprobación: deriva a "
                                f"'{SUPERVISOR}'.")
            abono = {"id_abono": len(self.ops.abonos) + 1, "id_reclamo": id_reclamo,
                     "id_movimiento": id_movimiento, "monto": round(float(monto), 2), "motivo": motivo}
            self.ops.abonos.append(abono)
        return {"abono_registrado": abono}

    def _validar_motivo(self, m: dict, motivo: str) -> None:
        if motivo == "cargo_duplicado":
            if m["tipo"] != "compra":
                raise ToolError("Solo una compra puede abonarse como cargo duplicado.")
            gemelos = self._q("""
                SELECT COUNT(*) AS n FROM movimientos
                WHERE id_tarjeta = ? AND comercio = ? AND id_movimiento <> ? AND estado = 'liquidado'
                  AND abs(monto - ?) < 0.01 AND fecha_hora BETWEEN ? AND ?""",
                [m["id_tarjeta"], m["comercio"], m["id_movimiento"], m["monto"],
                 m["fecha_hora"] - VENTANA_DUPLICADO, m["fecha_hora"] + VENTANA_DUPLICADO])[0]["n"]
            if not gemelos:
                raise ToolError("No hay otro cargo liquidado igual dentro de 10 minutos: no es un duplicado.")
        elif motivo == "recarga_no_acreditada":
            r = self._q("SELECT estado_operador FROM recargas WHERE id_movimiento = ?", [m["id_movimiento"]])
            if not r or r[0]["estado_operador"] != "fallida":
                raise ToolError("El operador confirmó la recarga: no procede el abono.")
        elif motivo == "membresia_exonerada":
            if m["tipo"] != "membresia" or m["fecha_hora"].date() > m["exonerada_hasta"]:
                raise ToolError("El cargo de membresía cae fuera del periodo de exoneración.")
        else:
            raise ToolError(f"Motivo no válido: {motivo}.")

    def derivar(self, id_reclamo: int, area: str, resumen: str) -> dict:
        self.reclamo(id_reclamo)
        if area not in AREAS_DERIVACION:
            raise ToolError(f"Área no válida. Opciones: {', '.join(AREAS_DERIVACION)}.")
        with self._lock:
            if self._cerrado(id_reclamo):
                raise ToolError("El reclamo ya está cerrado.")
            d = {"id_reclamo": id_reclamo, "area": area, "resumen": resumen[:600]}
            self.ops.derivaciones.append(d)
        return {"derivacion_registrada": d}

    def registrar_respuesta(self, id_reclamo: int, resultado: str, mensaje: str) -> dict:
        self.reclamo(id_reclamo)
        with self._lock:
            if self._cerrado(id_reclamo):
                raise ToolError("El reclamo ya tiene respuesta registrada.")
            propio = self.ops.del_reclamo(id_reclamo)
            if resultado == "procede_abonado" and not propio["abonos"]:
                raise ToolError("No hay abono registrado para este reclamo.")
            if resultado == "derivado" and not propio["derivaciones"]:
                raise ToolError("Primero deriva el reclamo con derivar_reclamo.")
            r = {"id_reclamo": id_reclamo, "resultado": resultado, "mensaje": mensaje}
            self.ops.respuestas.append(r)
        return {"respuesta_registrada": True, "resultado": resultado}

    def bloquear_tarjeta(self, id_cliente: int, motivo: str) -> dict:
        self.cliente(id_cliente)
        with self._lock:
            b = {"id_cliente": id_cliente, "motivo": motivo}
            self.ops.bloqueos.append(b)
        return {"tarjeta_bloqueada": True}


def crear_servidor(sistemas: Sistemas) -> MCPServer:
    """Registra las herramientas sobre una instancia de Sistemas."""
    srv = MCPServer("killa-sistemas", instructions=(
        "Sistemas de Killa para atender reclamos de la tarjeta de crédito. Montos en soles. "
        "Los datos personales vienen enmascarados."))

    @srv.tool(annotations=LECTURA)
    def ver_reclamo(id_reclamo: int) -> dict:
        """Devuelve el reclamo: código, cliente, fecha, canal y texto (con datos personales enmascarados)."""
        return sistemas.reclamo(id_reclamo)

    @srv.tool(annotations=LECTURA)
    def ver_cliente(id_cliente: int) -> dict:
        """Datos del cliente y su tarjeta: estado, línea, fecha de emisión y hasta cuándo está exonerada la membresía."""
        return sistemas.cliente(id_cliente)

    @srv.tool(annotations=LECTURA)
    def listar_movimientos(id_cliente: int, desde: str, hasta: str, comercio: str = "") -> dict:
        """Movimientos de la tarjeta entre dos fechas (YYYY-MM-DD, ambas incluidas), del más reciente al más
        antiguo. `comercio` filtra por parte del nombre. Tipos: compra, recarga, membresia."""
        return sistemas.movimientos(id_cliente, desde, hasta, comercio)

    @srv.tool(annotations=LECTURA)
    def revisar_cargo(id_movimiento: int) -> dict:
        """Hechos de un movimiento: otros cargos del mismo comercio en 48 horas (con minutos de diferencia y
        si tienen el mismo monto), estado de la recarga según el operador, si una membresía cayó dentro de la
        exoneración y si ya tiene abonos."""
        return sistemas.revisar_cargo(id_movimiento)

    @srv.tool(annotations=LECTURA)
    def listar_pagos(id_cliente: int, desde: str, hasta: str) -> dict:
        """Pagos a la tarjeta entre dos fechas (YYYY-MM-DD), con canal, si ya se aplicaron a la deuda y cuándo."""
        return sistemas.pagos(id_cliente, desde, hasta)

    @srv.tool(annotations=ESCRITURA)
    def emitir_abono(id_reclamo: int, id_movimiento: int, monto: float, motivo: Motivo) -> dict:
        """Abona a la tarjeta el monto de un movimiento. Solo procede con sustento en los datos: cargo duplicado
        (otro cargo liquidado igual en 10 minutos), recarga que el operador reporta fallida o membresía cobrada
        dentro de la exoneración. Tope S/ 500; sobre eso hay que derivar al supervisor."""
        return sistemas.emitir_abono(id_reclamo, id_movimiento, monto, motivo)

    @srv.tool(annotations=ESCRITURA)
    def derivar_reclamo(id_reclamo: int, area: Area, resumen: str) -> dict:
        """Deriva el reclamo a un área con un resumen de lo verificado. Fraude: consumos que el cliente no
        reconoce. Operaciones: pagos no aplicados. Contracargos: compras no recibidas. Supervisor: abonos sobre
        el tope o casos que requieren revisión humana."""
        return sistemas.derivar(id_reclamo, area, resumen)

    @srv.tool(annotations=ESCRITURA)
    def registrar_respuesta(id_reclamo: int, resultado: ResultadoReclamo, mensaje: str) -> dict:
        """Registra la respuesta al cliente y cierra la atención. `resultado`: procede_abonado (hay abono),
        no_procede (los datos no lo sustentan) o derivado (se derivó a un área)."""
        return sistemas.registrar_respuesta(id_reclamo, resultado, mensaje)

    @srv.tool(annotations=DESTRUCTIVA)
    def bloquear_tarjeta(id_cliente: int, motivo: str) -> dict:
        """Bloquea la tarjeta del cliente. Uso exclusivo de Prevención de fraude."""
        return sistemas.bloquear_tarjeta(id_cliente, motivo)

    return srv
