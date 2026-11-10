"""
Permisos por herramienta, aplicados en el host antes de llamar al servidor MCP.

Un perfil dice qué herramientas ve el modelo y con qué límites. Además, toda
llamada queda acotada al reclamo que se está atendiendo: el modelo no puede
consultar a otro cliente ni abonar un movimiento que no apareció en lo que
ya revisó. Cada decisión se guarda para la traza de auditoría.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LECTURA = {"ver_reclamo", "ver_cliente", "listar_movimientos", "revisar_cargo", "listar_pagos"}


@dataclass(frozen=True)
class Perfil:
    nombre: str
    herramientas: frozenset[str]
    tope_abono: float = 0.0
    max_abonos: int = 0
    max_llamadas: int = 14


PERFILES = {
    "asistente_reclamos": Perfil(
        "asistente_reclamos",
        frozenset(LECTURA | {"emitir_abono", "derivar_reclamo", "registrar_respuesta"}),
        tope_abono=500.0, max_abonos=1),
    # si el reclamo trae instrucciones para el asistente, no se abona nada: va a revisión humana
    "revision_humana": Perfil(
        "revision_humana",
        frozenset(LECTURA | {"derivar_reclamo", "registrar_respuesta"})),
    "solo_lectura": Perfil("solo_lectura", frozenset(LECTURA)),
}


@dataclass
class Decision:
    herramienta: str
    permitido: bool
    razon: str = ""


@dataclass
class Control:
    """Estado del permiso durante la atención de un reclamo."""

    perfil: Perfil
    id_reclamo: int
    id_cliente: int
    movimientos_vistos: set[int] = field(default_factory=set)
    llamadas: int = 0
    abonos: int = 0
    decisiones: list[Decision] = field(default_factory=list)

    def visibles(self, herramientas: list[dict]) -> list[dict]:
        """Filtra la lista del servidor: el modelo solo ve lo que su perfil permite."""
        return [h for h in herramientas if h["name"] in self.perfil.herramientas]

    def autorizar(self, nombre: str, entrada: dict) -> Decision:
        d = self._evaluar(nombre, entrada)
        self.decisiones.append(d)
        if d.permitido:
            self.llamadas += 1
        return d

    def _evaluar(self, nombre: str, entrada: dict) -> Decision:
        if nombre not in self.perfil.herramientas:
            return Decision(nombre, False, f"La herramienta {nombre} no está habilitada para el perfil "
                                           f"{self.perfil.nombre}.")
        if self.llamadas >= self.perfil.max_llamadas:
            return Decision(nombre, False, "Se llegó al máximo de llamadas para este reclamo.")
        if "id_reclamo" in entrada and _entero(entrada["id_reclamo"]) != self.id_reclamo:
            return Decision(nombre, False, f"Solo puedes operar sobre el reclamo {self.id_reclamo}.")
        if "id_cliente" in entrada and _entero(entrada["id_cliente"]) != self.id_cliente:
            return Decision(nombre, False, f"Solo puedes consultar al cliente {self.id_cliente}.")
        if nombre == "revisar_cargo" and _entero(entrada.get("id_movimiento")) not in self.movimientos_vistos:
            return Decision(nombre, False, "Ese movimiento no salió en listar_movimientos para este cliente.")
        if nombre == "emitir_abono":
            if _entero(entrada.get("id_movimiento")) not in self.movimientos_vistos:
                return Decision(nombre, False, "Solo se abona un movimiento que ya revisaste.")
            if self.abonos >= self.perfil.max_abonos:
                return Decision(nombre, False, "Ya hay un abono en este reclamo.")
            try:
                monto = float(entrada.get("monto", 0))
            except (TypeError, ValueError):
                return Decision(nombre, False, "Monto no válido.")
            if monto > self.perfil.tope_abono:
                return Decision(nombre, False, f"El monto supera el tope de S/ {self.perfil.tope_abono:.0f} del "
                                               "perfil: deriva al Supervisor de reclamos.")
        return Decision(nombre, True)

    def registrar_salida(self, nombre: str, salida: dict, error: bool) -> None:
        """Toma nota de los movimientos que el modelo ya vio y de los abonos hechos."""
        if error:
            return
        if nombre == "listar_movimientos":
            self.movimientos_vistos |= {m["id_movimiento"] for m in salida.get("movimientos", [])}
        elif nombre == "revisar_cargo":
            self.movimientos_vistos |= {c["id_movimiento"] for c in salida.get("otros_cargos_mismo_comercio_48h", [])}
        elif nombre == "emitir_abono":
            self.abonos += 1


def _entero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None
