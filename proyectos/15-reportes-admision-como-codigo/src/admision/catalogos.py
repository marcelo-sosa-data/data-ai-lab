"""Catálogos oficiales de Admisión y sinónimos de encabezados de cada export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Campania:
    codigo: str
    inicio: date
    cierre: date
    anterior_comparable: str | None   # misma época del año anterior


CAMPANIAS = {
    "2026-1": Campania("2026-1", date(2025, 8, 4), date(2026, 3, 20), None),
    "2026-2": Campania("2026-2", date(2026, 3, 30), date(2026, 8, 14), None),
    "2027-1": Campania("2027-1", date(2026, 8, 3), date(2027, 3, 19), "2026-1"),
}
CAMPANIA_ACTUAL = "2027-1"
CORTE_ACTUAL = date(2026, 11, 15)

MODALIDADES = ["Examen de admisión", "Quinto superior", "Primeros puestos", "Traslado externo",
               "Adultos que trabajan", "Beca Mirasol"]
CARRERAS = ["Ingeniería Industrial", "Ingeniería de Sistemas", "Ingeniería Civil", "Administración",
            "Contabilidad", "Marketing", "Psicología", "Derecho"]
SEDES = ["Lima Norte", "Lima Centro", "Arequipa"]
CANALES = ["Colegios en convenio", "Ferias escolares", "Referidos", "Web", "WhatsApp", "Redes sociales"]
ESTADOS = {"INSCRITO": "Inscrito", "ANULADO": "Anulado", "INGRESO": "Ingresó", "NO INGRESO": "No ingresó"}

# documentos que sistemas usa para probar el formulario
DOCUMENTOS_PRUEBA = {"00000000", "12345678", "11111111", "99999999"}

# nombre normalizado del encabezado -> columna estándar
SINONIMOS = {
    "inscripciones": {
        "codigo_postulante": ["codigo", "codigo_postulante", "cod_postulante"],
        "tipo_documento": ["tipo_doc", "tipo_documento"],
        "documento": ["nro_documento", "documento", "num_documento", "numero_documento"],
        "nombre_completo": ["apellidos_y_nombres", "nombre_completo"],
        "celular": ["celular", "telefono_celular"],
        "modalidad": ["modalidad", "modalidad_ingreso", "modalidad_de_ingreso"],
        "carrera": ["carrera", "programa"],
        "sede": ["sede", "campus"],
        "fecha_inscripcion": ["fecha_inscripcion"],
        "estado": ["estado", "estado_postulante"],
        "puntaje": ["puntaje", "nota"],
        "fecha_resultado": ["fecha_resultado"],
        "fecha_actualizacion": ["fecha_actualizacion", "ultima_actualizacion"],
    },
    "interesados": {
        "id_lead": ["id_lead", "id"],
        "fecha_registro": ["fecha_de_registro", "fecha_registro"],
        "nombre": ["nombre", "nombre_completo"],
        "documento": ["documento", "dni"],
        "celular": ["celular", "telefono"],
        "canal": ["canal", "fuente"],
        "carrera": ["carrera_de_interes", "carrera"],
        "sede": ["sede_de_interes", "sede"],
    },
    "pagos": {
        "fecha_pago": ["fecha", "fecha_pago", "fecha_de_pago"],
        "documento_pagador": ["documento_pagador", "doc_pagador"],
        "pagador": ["pagador", "nombre_pagador"],
        "concepto": ["concepto"],
        "referencia": ["referencia", "observacion"],
        "monto": ["monto", "importe"],
    },
}
OPCIONALES = {"inscripciones": {"celular", "puntaje"}, "interesados": {"documento", "celular"},
              "pagos": {"pagador", "referencia"}}
