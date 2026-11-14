"""Lógica pura del flujo: agregado por minuto y regla de saturación.

No depende de Kafka, así que la usan igual el procesador en streaming,
la simulación del proceso actual y los tests. Todo lo que se guarda en el
estado de Quix es un dict serializable a JSON.
"""

from __future__ import annotations

from .config import Regla

TIPOS = ("creado", "asignado", "entregado", "cancelado")


def agregado_inicial(evento: dict | None = None, demora_s: float = 360.0) -> dict:
    agg = {"creados": 0, "asignados": 0, "entregados": 0, "cancelados": 0,
           "demoradas": 0, "suma_espera_s": 0.0}
    if evento is not None:
        agg = acumular(agg, evento, demora_s)
    return agg


def acumular(agg: dict, evento: dict, demora_s: float = 360.0) -> dict:
    """Suma un evento al agregado de su ventana."""
    tipo = evento["tipo"]
    if tipo not in TIPOS:
        return agg
    agg[tipo + "s"] += 1
    if tipo == "asignado":
        espera = float(evento.get("espera_asignacion_s") or 0.0)
        agg["suma_espera_s"] += espera
        if espera > demora_s:
            agg["demoradas"] += 1
    return agg


def fila_minuto(zona: str, inicio_ms: int, fin_ms: int, agg: dict) -> dict:
    asign = agg["asignados"]
    return {
        "zona": zona,
        "inicio_ms": inicio_ms,
        "fin_ms": fin_ms,
        **agg,
        "espera_media_s": round(agg["suma_espera_s"] / asign, 1) if asign else None,
    }


# --------------------------------------------------------------- deduplicación

class EstadoDict:
    """Mismo contrato get/set que el estado de Quix, para tests y simulaciones."""

    def __init__(self):
        self.datos: dict = {}

    def get(self, clave, default=None):
        return self.datos.get(clave, default)

    def set(self, clave, valor):
        self.datos[clave] = valor


def es_evento_nuevo(estado, evento_id: str) -> bool:
    """True la primera vez que aparece el id en la zona; lo marca como visto.

    `estado` es el State de Quix (por clave de mensaje, o sea por zona) o un
    EstadoDict. Los reintentos de la app llegan con el mismo evento_id.
    """
    clave = "visto:" + evento_id
    if estado.get(clave) is not None:
        return False
    estado.set(clave, 1)
    return True


# --------------------------------------------------------------- pendientes

def actualizar_pendientes(pend: dict, cerrados: dict, evento: dict, reloj_ms: int,
                          vencido_s: float = 3600.0) -> None:
    """Lleva la lista de pedidos sin motorizado de la zona.

    Un `creado` entra, un `asignado` o `cancelado` sale. Si el cierre llega
    antes que el `creado` (pasa cuando la app del cliente se atrasa), el
    pedido queda en `cerrados` para no abrirlo después. Lo que lleva más de
    `vencido_s` se descarta: es un pedido cuyo cierre se perdió.
    """
    pid, tipo = evento["pedido_id"], evento["tipo"]
    if tipo == "creado":
        if pid not in cerrados:
            pend[pid] = evento["ts_ms"]
    elif tipo in ("asignado", "cancelado"):
        if pend.pop(pid, None) is None:
            cerrados[pid] = reloj_ms
    limite = reloj_ms - vencido_s * 1000
    for d in (pend, cerrados):
        for k in [k for k, v in d.items() if v < limite]:
            del d[k]


def minuto_nuevo(ultimo_ms: int | None, reloj_ms: int) -> int | None:
    """Si el reloj pasó a otro minuto, devuelve el inicio de ese minuto (el corte)."""
    corte = reloj_ms - reloj_ms % 60_000
    if ultimo_ms is None or corte > ultimo_ms:
        return corte
    return None


def sin_motorizado(pend: dict, corte_ms: int, espera_s: float) -> int:
    """Pedidos creados antes de `corte_ms - espera_s` que siguen sin motorizado."""
    tope = corte_ms - espera_s * 1000
    return sum(1 for ts in pend.values() if ts <= tope)


# --------------------------------------------------------------- regla

def estado_inicial() -> dict:
    return {"en_alerta": False, "racha_mala": 0, "racha_buena": 0, "abierta_ms": None, "pico": 0}


def evaluar_minuto(estado: dict, fila: dict, regla: Regla, ahora_ms: int) -> dict | None:
    """Actualiza el estado de la zona con una foto de la cola.

    `fila["sin_motorizado"]` es la cola en el corte `fila["inicio_ms"]` y
    `ahora_ms` el momento en que el flujo la emitió. Devuelve un evento al abrir o
    cerrar la alerta, o None.
    """
    cola = fila["sin_motorizado"]
    if cola >= regla.umbral_sin_motorizado:
        estado["racha_mala"] += 1
        estado["racha_buena"] = 0
    else:
        estado["racha_buena"] += 1
        estado["racha_mala"] = 0

    base = {"zona": fila["zona"], "minuto_ms": fila["inicio_ms"], "detectado_ms": ahora_ms,
            "sin_motorizado": cola}
    if not estado["en_alerta"] and estado["racha_mala"] >= regla.minutos_para_abrir:
        estado.update(en_alerta=True, abierta_ms=ahora_ms, pico=cola)
        return {**base, "accion": "abrir", "abierta_ms": ahora_ms, "pico": cola}
    if estado["en_alerta"]:
        estado["pico"] = max(estado["pico"], cola)
        if estado["racha_buena"] >= regla.minutos_para_cerrar:
            estado["en_alerta"] = False
            return {**base, "accion": "cerrar", "abierta_ms": estado["abierta_ms"],
                    "pico": estado["pico"]}
    return None


def evaluar_serie(filas: list[dict], regla: Regla, clave_tiempo: str = "emitido_ms") -> list[dict]:
    """Aplica la regla a una serie de minutos de una zona, en orden. Para simulaciones."""
    estado, alertas = estado_inicial(), []
    for f in filas:
        a = evaluar_minuto(estado, f, regla, f[clave_tiempo])
        if a:
            alertas.append(a)
    return alertas
