"""
Los experimentos de 2026 como los registró el equipo de producto: hipótesis, ventana,
métrica primaria y guardrails con su margen de no inferioridad. El análisis lee de
aquí qué medir y cómo decidir; el generador, cuándo corre cada uno.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Guardrail:
    metrica: str
    # cambio relativo máximo tolerado en la dirección mala (0.03 = 3%)
    margen: float


@dataclass(frozen=True)
class Experimento:
    id: str
    nombre: str
    hipotesis: str
    inicio: str
    fin: str
    primaria: str
    guardrails: tuple[Guardrail, ...] = field(default_factory=tuple)
    reparto: float = 0.5

    @property
    def sal(self) -> str:
        return self.id.lower()


# Métricas por usuario expuesto, desde su primera exposición hasta el fin de la ventana.
# "mejor" indica la dirección buena; las de tipo ratio se analizan con el método delta.
METRICAS = {
    "pedidos": {"nombre": "pedidos por usuario", "tipo": "media", "mejor": +1, "formato": ".3f"},
    "conversion": {"nombre": "conversión", "tipo": "media", "mejor": +1, "formato": ".1%"},
    "gmv": {"nombre": "GMV por usuario (S/)", "tipo": "media", "mejor": +1, "formato": ".2f"},
    "margen": {"nombre": "margen por usuario (S/)", "tipo": "media", "mejor": +1, "formato": ".2f"},
    "ticket": {"nombre": "ticket promedio (S/)", "tipo": "ratio", "num": "gmv", "den": "pedidos",
               "mejor": +1, "formato": ".2f"},
    "cancelacion": {"nombre": "tasa de cancelación", "tipo": "ratio", "num": "cancelados",
                    "den": "pedidos_creados", "mejor": -1, "formato": ".2%"},
}

EXPERIMENTOS = [
    Experimento(
        "EXP-01", "Checkout en una sola pantalla",
        "Juntar dirección, pago y confirmación en una pantalla sube los pedidos por usuario.",
        "2026-03-02", "2026-03-29", "pedidos",
        (Guardrail("cancelacion", 0.10), Guardrail("ticket", 0.02)),
    ),
    Experimento(
        "EXP-02", "Envío gratis desde S/ 35",
        "Quitar la tarifa de envío desde S/ 35 sube el GMV sin comerse el margen.",
        "2026-04-20", "2026-05-17", "gmv",
        (Guardrail("margen", 0.03), Guardrail("cancelacion", 0.10)),
    ),
    Experimento(
        "EXP-03", "Recomendados en el carrito",
        "Sugerir un complemento (bebida, postre) en el carrito sube el GMV por usuario.",
        "2026-06-08", "2026-07-05", "gmv",
        (Guardrail("cancelacion", 0.10), Guardrail("pedidos", 0.02)),
    ),
    Experimento(
        "EXP-04", "ETA optimista",
        "Mostrar el tiempo de entrega del percentil 40 en vez del 60 sube los pedidos.",
        "2026-07-20", "2026-08-16", "pedidos",
        (Guardrail("cancelacion", 0.10), Guardrail("margen", 0.03)),
    ),
    Experimento(
        "EXP-05", "Propina sugerida",
        "Sugerir S/ 2 de propina al rider no cambia cuánto piden los usuarios.",
        "2026-08-31", "2026-09-27", "pedidos",
        (Guardrail("cancelacion", 0.10), Guardrail("gmv", 0.02)),
    ),
]

# Periodo sin experimentos: sirve para el estudio A/A
PERIODO_AA = ("2026-01-26", "2026-02-22")
DIAS_PRE = 28


def por_id(id_exp: str) -> Experimento:
    for e in EXPERIMENTOS:
        if e.id == id_exp.upper():
            return e
    raise KeyError(f"No existe el experimento {id_exp}. Opciones: {', '.join(e.id for e in EXPERIMENTOS)}")
