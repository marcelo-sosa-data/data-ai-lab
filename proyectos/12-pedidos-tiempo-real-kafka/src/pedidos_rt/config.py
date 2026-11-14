"""Parámetros del flujo: broker, tópicos, ventanas y la regla de saturación."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DIR_DATOS = Path(os.getenv("PEDIDOS_DATOS", RAIZ / "datos"))


@dataclass(frozen=True)
class Topicos:
    eventos: str = "pedidos.eventos"
    minuto: str = "pedidos.metricas-minuto"
    alertas: str = "pedidos.alertas"
    particiones: int = 6


@dataclass(frozen=True)
class Regla:
    """Cuándo una zona está saturada.

    En cada cambio de minuto se cuentan los pedidos que llevan más de
    `espera_sin_motorizado_s` sin motorizado (la cola). La zona entra en alerta con
    `minutos_para_abrir` minutos seguidos sobre el umbral y sale con
    `minutos_para_cerrar` minutos seguidos por debajo, para que la alerta
    no se prenda y apague cada minuto.

    `umbral_demoradas` es la regla del tablero actual: parte de las
    asignaciones del bloque que esperó más de `demora_s`.
    """

    espera_sin_motorizado_s: float = 180.0
    umbral_sin_motorizado: int = 7
    minutos_para_abrir: int = 2
    minutos_para_cerrar: int = 5
    demora_s: float = 360.0
    umbral_demoradas: float = 0.35
    minimo_asignaciones: int = 10
    pendiente_vencido_s: float = 3600.0


@dataclass(frozen=True)
class Ajustes:
    broker: str = field(default_factory=lambda: os.getenv("KAFKA_BROKER", "localhost:19092"))
    topicos: Topicos = field(default_factory=Topicos)
    regla: Regla = field(default_factory=Regla)
    ventana_ms: int = 60_000
    gracia_ms: int = 60_000
    dir_salida: Path = field(default_factory=lambda: DIR_DATOS / "salida")
    dir_estado: Path = field(default_factory=lambda: DIR_DATOS / "estado")
