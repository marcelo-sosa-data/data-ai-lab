"""Nombres de actividades, áreas, plazos del reglamento y fechas del calendario académico."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

CONVALIDACION = "Convalidación de cursos"
RETIRO = "Retiro de curso"

# actividades tal como las registra el sistema de trámites
REGISTRAR = "Registrar solicitud"
REVISAR_EXP = "Revisar expediente"
OBSERVAR_EXP = "Observar expediente"
SUBSANAR = "Subsanar observación"
EVALUAR = "Evaluar sílabos"
OBSERVAR_SIL = "Observar sílabos"
EMITIR = "Emitir resolución"
FIRMAR = "Firmar resolución"
VERIFICAR_PAGO = "Verificar pago"
OBSERVAR_PAGO = "Observar pago"
PAGAR = "Pagar derecho"
REGISTRAR_CONV = "Registrar convalidación"
NOTIFICAR = "Notificar resultado"
ARCHIVAR = "Archivar por abandono"

REVISAR_SOL = "Revisar solicitud"
OBSERVAR_SOL = "Observar solicitud"
VISTO_BUENO = "Visto bueno de dirección"
RECHAZAR_DIR = "Rechazar en dirección"
VERIFICAR_DEUDA = "Verificar deuda"
OBSERVAR_DEUDA = "Observar deuda"
PAGAR_DEUDA = "Pagar deuda"
APROBAR_RETIRO = "Aprobar retiro"
DEVOLVER_PLAZO = "Devolver por plazo vencido"
EMITIR_EXCEPCION = "Emitir resolución de excepción"
RECHAZAR_EXT = "Rechazar por extemporáneo"

ESTUDIANTE = "Estudiante"
SECRETARIA = "Secretaría Académica"
DIRECCION = "Dirección de Carrera"
DECANATO = "Decanato"
TESORERIA = "Tesorería"
REGISTROS = "Registros Académicos"
SISTEMA = "Sistema"

AREAS = [SECRETARIA, DIRECCION, DECANATO, TESORERIA, REGISTROS, ESTUDIANTE]

# actividades que el sistema solo marca al terminar (no hay hora de inicio)
SIN_INICIO = {REGISTRAR, SUBSANAR, PAGAR, PAGAR_DEUDA, VERIFICAR_PAGO, VERIFICAR_DEUDA,
              FIRMAR, NOTIFICAR, OBSERVAR_EXP, OBSERVAR_SIL, OBSERVAR_PAGO, OBSERVAR_SOL,
              OBSERVAR_DEUDA, RECHAZAR_EXT, RECHAZAR_DIR, ARCHIVAR}

# actividades que son repetición o corrección de trabajo ya hecho
OBSERVACIONES = {OBSERVAR_EXP, OBSERVAR_SIL, OBSERVAR_PAGO, OBSERVAR_SOL, OBSERVAR_DEUDA,
                 DEVOLVER_PLAZO}

CARRERAS = {
    # carrera: peso en el volumen de trámites
    "Derecho": 0.18, "Administración": 0.17, "Ingeniería Industrial": 0.16,
    "Contabilidad": 0.12, "Psicología": 0.11, "Ingeniería de Sistemas": 0.11,
    "Arquitectura": 0.08, "Comunicaciones": 0.07,
}
SEDES = {"Lima Centro": 0.46, "Lima Norte": 0.34, "Arequipa": 0.20}

# plazos del reglamento de trámites, en días hábiles desde el registro
PLAZO_DIAS = {CONVALIDACION: 15, RETIRO: 7}


@dataclass(frozen=True)
class Semestre:
    nombre: str
    inicio_clases: datetime
    limite_retiro: datetime


SEMESTRES = [
    Semestre("2026-1", datetime(2026, 3, 16), datetime(2026, 5, 22, 23, 59)),
    Semestre("2026-2", datetime(2026, 8, 17), datetime(2026, 10, 23, 23, 59)),
]

INICIO_LOG = datetime(2026, 1, 5)
CORTE = datetime(2026, 11, 20, 23, 59)
# la regla se estima con lo registrado en el primer semestre y se prueba en el segundo
INICIO_PRUEBA = datetime(2026, 7, 1)
FIN_PRUEBA = datetime(2026, 10, 31, 23, 59)


def semestre_de(fecha) -> Semestre:
    return SEMESTRES[0] if fecha < datetime(2026, 7, 1) else SEMESTRES[1]


@dataclass(frozen=True)
class Reglas:
    """Reglas del proceso. Por defecto, el proceso actual."""

    pago_al_inicio: bool = False            # pago y deuda se verifican al registrar, en paralelo
    observacion_a_direccion: bool = False   # lo que observa Dirección vuelve a Dirección
    visto_bueno_solo_becados: bool = False  # el retiro pasa por Dirección solo si es becado
    dias_firma: tuple[int, ...] = field(default=(4,))  # 0=lunes ... 4=viernes


ESCENARIOS: dict[str, tuple[str, Reglas]] = {
    "actual": ("Proceso actual", Reglas()),
    "e1": ("Pago y deuda al inicio", Reglas(pago_al_inicio=True)),
    "e2": ("+ observación vuelve a Dirección",
           Reglas(pago_al_inicio=True, observacion_a_direccion=True)),
    "e3": ("+ visto bueno solo a becados",
           Reglas(pago_al_inicio=True, observacion_a_direccion=True, visto_bueno_solo_becados=True)),
    "e4": ("+ firma martes y viernes",
           Reglas(pago_al_inicio=True, observacion_a_direccion=True, visto_bueno_solo_becados=True,
                  dias_firma=(1, 4))),
}
