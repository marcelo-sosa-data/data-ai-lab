"""
Genera los exports crudos del sistema académico de la "Universidad Mirasol",
una universidad privada ficticia con sedes en Lima Norte, Lima Centro y Arequipa.

Simula seis años de cohortes (2021-1 a 2026-2) pero exporta solo lo que el
área de datos recibe: los periodos 2024-1 a 2026-2, con fecha de corte en
octubre de 2026 (el ciclo 2026-2 está en curso).

Patrones que se pueden encontrar en los datos:
  - la matrícula se hace por turnos según orden de mérito: los mejores
    promedios se matriculan primero; los que tienen deuda, al final
  - las secciones de la mañana se llenan y las de la noche sobran
  - las clases virtuales crecen cada ciclo
  - Matemática I, Cálculo I y Física I son cursos filtro
  - quien termina el ciclo con cuotas impagas o con promedio bajo tiene
    mucha menos probabilidad de matricularse el ciclo siguiente
  - en 2026-2 ingresan menos alumnos y sube la morosidad

Y los problemas típicos de un export real, que el pipeline tiene que limpiar
(se registran en _anomalias.json para verificar que se detectan todos):
  - doble clic: el mismo evento repetido a segundos de distancia
  - códigos de alumno en minúsculas o con espacios
  - eventos de secciones de prueba del área de sistemas
  - retiros sin inscripción previa (bug conocido del módulo antiguo)
  - fechas en formato dd/mm/yyyy cuando el evento se registró en ventanilla
  - montos como texto ("S/ 1,250.00")
  - notas "NSP" (no se presentó)
  - varias versiones del mismo alumno en el maestro

Uso:
    python datos/generar_datos.py                   # ~15 s, ~25 MB de CSV
    python datos/generar_datos.py --escala 0.05     # versión chica para pruebas
    python datos/generar_datos.py --corte 2026-09-15
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).parents[1]
SALIDA_DEFECTO = Path(__file__).parent / "raw"
CALENDARIO = RAIZ / "dbt_matricula" / "seeds" / "calendario_academico.csv"
CORTE_DEFECTO = date(2026, 10, 24)
PRIMER_PERIODO_EXPORTADO = "2024-1"

# --------------------------------------------------------------------------
# Catálogos
# --------------------------------------------------------------------------

SEDES = {"LN": "Lima Norte", "LC": "Lima Centro", "AQ": "Arequipa"}
PESO_SEDE = {"LN": 0.45, "LC": 0.35, "AQ": 0.20}
TURNOS = {"M": "Mañana", "T": "Tarde", "N": "Noche"}

DISTRITOS = {
    "LN": ["Los Olivos", "Comas", "Independencia", "San Martín de Porres", "Puente Piedra", "Carabayllo"],
    "LC": ["Cercado de Lima", "Breña", "Jesús María", "La Victoria", "San Juan de Lurigancho", "Rímac", "San Miguel"],
    "AQ": ["Cercado", "Cayma", "Yanahuara", "José Luis Bustamante y Rivero", "Paucarpata", "Cerro Colorado"],
}

# código, nombre, facultad, peso en ingresantes, pensión base Lima 2024 (S/)
CARRERAS = [
    ("IND", "Ingeniería Industrial", "Ingeniería", 0.17, 1180),
    ("SIS", "Ingeniería de Sistemas", "Ingeniería", 0.14, 1180),
    ("CIV", "Ingeniería Civil", "Ingeniería", 0.10, 1250),
    ("ADM", "Administración", "Negocios", 0.15, 980),
    ("CON", "Contabilidad", "Negocios", 0.10, 940),
    ("MKT", "Marketing", "Negocios", 0.08, 990),
    ("PSI", "Psicología", "Ciencias Humanas y Derecho", 0.14, 1020),
    ("DER", "Derecho", "Ciencias Humanas y Derecho", 0.12, 1080),
]

# código, nombre, créditos, dificultad (negativo = baja la nota promedio)
CURSOS_GENERALES = [
    ("GEN101", "Comunicación I", 3, 0.5),
    ("GEN102", "Desarrollo Personal", 2, 1.5),
    ("GEN103", "Matemática Básica", 4, -1.6),
    ("GEN104", "Comunicación II", 3, 0.3),
    ("GEN105", "Realidad Nacional", 2, 1.0),
    ("GEN106", "Estadística General", 4, -1.4),
    ("GEN107", "Ética y Ciudadanía", 2, 1.2),
    ("GEN108", "Metodología de la Investigación", 3, 0.0),
    ("GEN109", "Seminario de Tesis I", 4, -0.3),
    ("GEN110", "Seminario de Tesis II", 4, -0.5),
    ("GEN111", "Prácticas Preprofesionales", 6, 1.5),
    ("GEN112", "Inglés I", 2, 0.8),
    ("GEN113", "Inglés II", 2, 0.5),
    ("GEN114", "Gestión de Proyectos", 3, 0.2),
]
CURSOS_FACULTAD = {
    "Ingeniería": [
        ("ING101", "Matemática I", 4, -3.4),
        ("ING102", "Química General", 4, -1.5),
        ("ING103", "Física I", 4, -2.9),
        ("ING104", "Cálculo I", 4, -3.1),
        ("ING105", "Cálculo II", 4, -2.0),
        ("ING106", "Física II", 4, -2.0),
        ("ING107", "Programación I", 4, -1.0),
        ("ING108", "Estadística y Probabilidades", 4, -1.5),
        ("ING109", "Dibujo de Ingeniería", 3, 0.5),
        ("ING110", "Economía General", 3, 0.0),
    ],
    "Negocios": [
        ("NEG101", "Introducción a los Negocios", 3, 1.0),
        ("NEG102", "Contabilidad General", 4, -2.2),
        ("NEG103", "Microeconomía", 4, -1.8),
        ("NEG104", "Macroeconomía", 4, -1.2),
        ("NEG105", "Matemática Financiera", 4, -2.5),
        ("NEG106", "Derecho Empresarial", 3, 0.3),
        ("NEG107", "Gestión del Talento", 3, 0.8),
        ("NEG108", "Estadística Aplicada a los Negocios", 4, -1.3),
    ],
    "Ciencias Humanas y Derecho": [
        ("HUM101", "Filosofía", 3, 0.2),
        ("HUM102", "Sociología", 3, 0.5),
        ("HUM103", "Lógica", 3, -1.6),
        ("HUM104", "Antropología Social", 3, 0.6),
        ("HUM105", "Pensamiento Crítico", 3, 0.4),
        ("HUM106", "Historia del Perú", 3, 0.7),
        ("HUM107", "Redacción Académica", 3, 0.3),
        ("HUM108", "Ciudadanía y Derechos Humanos", 3, 1.0),
    ],
}
GENERALES_POR_FACULTAD = {
    "Ingeniería": ["GEN101", "GEN102", "GEN104", "GEN105", "GEN107", "GEN108", "GEN112", "GEN113"],
    "Negocios": ["GEN101", "GEN102", "GEN103", "GEN104", "GEN105", "GEN106", "GEN107", "GEN108", "GEN112", "GEN113"],
    "Ciencias Humanas y Derecho": ["GEN101", "GEN102", "GEN103", "GEN104", "GEN105", "GEN106", "GEN107",
                                   "GEN108", "GEN112", "GEN113"],
}
ESPECIALIDAD = {
    "IND": ["Introducción a la Ingeniería Industrial", "Procesos Industriales", "Investigación de Operaciones I",
            "Investigación de Operaciones II", "Ingeniería de Métodos", "Gestión de la Calidad",
            "Logística y Cadena de Suministro", "Planeamiento y Control de Operaciones",
            "Seguridad y Salud Ocupacional", "Simulación de Sistemas", "Ingeniería Económica",
            "Costos y Presupuestos", "Diseño de Plantas", "Lean Manufacturing"],
    "SIS": ["Introducción a la Ingeniería de Sistemas", "Programación II", "Estructuras de Datos", "Base de Datos I",
            "Base de Datos II", "Sistemas Operativos", "Redes de Computadoras", "Ingeniería de Software I",
            "Ingeniería de Software II", "Arquitectura de Computadoras", "Inteligencia Artificial",
            "Seguridad Informática", "Computación en la Nube", "Analítica de Datos"],
    "CIV": ["Introducción a la Ingeniería Civil", "Estática", "Dinámica", "Resistencia de Materiales I",
            "Resistencia de Materiales II", "Topografía", "Mecánica de Suelos I", "Mecánica de Fluidos",
            "Análisis Estructural I", "Concreto Armado I", "Tecnología del Concreto", "Hidrología",
            "Costos y Presupuestos de Obra", "Diseño Sismorresistente"],
    "ADM": ["Fundamentos de Administración", "Comportamiento Organizacional", "Marketing I",
            "Finanzas Corporativas I", "Gestión de Operaciones", "Planeamiento Estratégico", "Gestión Pública",
            "Emprendimiento", "Negocios Internacionales", "Finanzas Corporativas II", "Gestión de la Innovación",
            "Responsabilidad Social", "Dirección Comercial", "Simulación de Negocios"],
    "CON": ["Contabilidad Intermedia", "Contabilidad de Costos I", "Contabilidad de Costos II", "Tributación I",
            "Tributación II", "Auditoría Financiera I", "Auditoría Financiera II", "Contabilidad Gubernamental",
            "Análisis de Estados Financieros", "NIIF", "Finanzas I", "Peritaje Contable",
            "Contabilidad de Sociedades", "Sistemas Contables"],
    "MKT": ["Fundamentos de Marketing", "Comportamiento del Consumidor", "Investigación de Mercados I",
            "Investigación de Mercados II", "Marketing Digital", "Gestión de Marca", "Trade Marketing", "Precios",
            "Publicidad y Medios", "Analítica de Marketing", "Marketing de Servicios", "Canales de Distribución",
            "E-commerce", "Planeamiento de Marketing"],
    "PSI": ["Psicología General", "Procesos Psicológicos Básicos", "Psicología del Desarrollo I",
            "Psicología del Desarrollo II", "Neurociencias", "Psicometría I", "Psicometría II", "Psicopatología",
            "Psicología Social", "Psicología Organizacional", "Psicología Clínica", "Psicología Educativa",
            "Evaluación Psicológica", "Intervención en Crisis"],
    "DER": ["Introducción al Derecho", "Derecho Romano", "Derecho Constitucional I", "Derecho Civil I",
            "Derecho Civil II", "Derecho Penal I", "Derecho Penal II", "Derecho Procesal Civil", "Derecho Laboral",
            "Derecho Administrativo", "Derecho Comercial", "Derecho Tributario", "Derecho Internacional Público",
            "Litigación Oral"],
}
DIFICILES = {
    "Investigación de Operaciones I": -1.8, "Estructuras de Datos": -1.8, "Estática": -2.0,
    "Resistencia de Materiales I": -2.5, "Contabilidad de Costos I": -1.6, "Derecho Civil I": -1.5,
    "Psicometría I": -1.4, "Neurociencias": -1.2, "Finanzas Corporativas I": -1.3,
}
ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
CURSOS_POR_PLAN = 46
CURSOS_FINALES = ["GEN114", "GEN109", "GEN110", "GEN111"]

MAX_CREDITOS = 26
VACANTES = {"Presencial": 40, "Virtual": 60}
CUOTA_MATRICULA = 350


# --------------------------------------------------------------------------
# Estructuras internas de la simulación
# --------------------------------------------------------------------------

@dataclass
class Alumno:
    codigo: str
    carrera: str
    sede: str
    cohorte: str
    turno: str
    trabaja: bool
    rendimiento: float
    riesgo_pago: float
    modalidad_ingreso: str
    fecha_nacimiento: date
    genero: str
    distrito: str
    aprobados: set = field(default_factory=set)
    activo: bool = True
    egresado: bool = False
    pausa: int = 0                 # 1 = no se matricula el próximo ciclo, 2 = puede volver
    ultimo_promedio: float | None = None
    deuda: list = field(default_factory=list)   # cuotas impagas (periodo, cuota, monto, vencimiento)
    matriculado_alguna_vez: bool = False


def leer_calendario() -> dict[str, dict[str, date]]:
    cal = {}
    with open(CALENDARIO, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            cal[fila["periodo"]] = {k: date.fromisoformat(v) for k, v in fila.items() if k != "periodo"}
    return cal


def armar_cursos(rng: np.random.Generator):
    """Devuelve el catálogo de cursos y el plan de estudios (carrera -> lista de (curso, ciclo))."""
    cursos = {}
    for cod, nom, cred, dif in CURSOS_GENERALES:
        cursos[cod] = dict(curso_cod=cod, curso=nom, creditos=cred, tipo="General", dificultad=dif)
    for fac, lista in CURSOS_FACULTAD.items():
        for cod, nom, cred, dif in lista:
            cursos[cod] = dict(curso_cod=cod, curso=nom, creditos=cred, tipo="Facultad", dificultad=dif)

    plan = {}
    for car, _, fac, _, _ in CARRERAS:
        esp = []
        for i, nom in enumerate(ESPECIALIDAD[car], 1):
            cod = f"{car}{100 + i}"
            dif = DIFICILES.get(nom, float(rng.uniform(-0.8, 1.2)))
            cursos[cod] = dict(curso_cod=cod, curso=nom, creditos=int(rng.choice([3, 4, 4, 5])),
                               tipo="Especialidad", dificultad=dif)
            esp.append(cod)
        base = GENERALES_POR_FACULTAD[fac] + [c[0] for c in CURSOS_FACULTAD[fac]]
        n_elect = CURSOS_POR_PLAN - len(base) - len(esp) - len(CURSOS_FINALES)
        elect = []
        for i in range(n_elect):
            cod = f"{car}E{i + 1:02d}"
            cursos[cod] = dict(curso_cod=cod, curso=f"Electivo de especialidad {ROMANOS[i]}", creditos=3,
                               tipo="Electivo", dificultad=float(rng.uniform(0.3, 1.5)))
            elect.append(cod)
        # orden: generales y de facultad intercalados con los primeros de especialidad
        orden = base[:8] + esp[:2] + base[8:] + esp[2:8] + elect[:4] + esp[8:] + elect[4:] + CURSOS_FINALES
        por_ciclo = math.ceil(len(orden) / 10)
        plan[car] = [(c, min(10, i // por_ciclo + 1)) for i, c in enumerate(orden)]
    return cursos, plan


def periodos_entre(desde: str, hasta: str) -> list[str]:
    out, (a, s) = [], map(int, desde.split("-"))
    while f"{a}-{s}" <= hasta:
        out.append(f"{a}-{s}")
        a, s = (a, 2) if s == 1 else (a + 1, 1)
    return out


def sigmoide(x: float) -> float:
    return 1 / (1 + math.exp(-x))


# --------------------------------------------------------------------------
# Generación
# --------------------------------------------------------------------------

def generar(salida: Path = SALIDA_DEFECTO, escala: float = 1.0, seed: int = 42,
            corte: date = CORTE_DEFECTO) -> Path:
    rng = np.random.default_rng(seed)
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    cal = leer_calendario()
    periodos = [p for p in cal if cal[p]["inicio_matricula"] <= corte]
    exportados = [p for p in periodos if p >= PRIMER_PERIODO_EXPORTADO]
    cursos, plan = armar_cursos(rng)
    car_info = {c[0]: c for c in CARRERAS}
    plan_ciclo = {car: dict(p) for car, p in plan.items()}

    alumnos: list[Alumno] = []
    correlativo = defaultdict(int)
    eventos, pagos, notas, secciones = [], [], [], []
    anom = dict.fromkeys(["matriculas_sobre_tope_creditos", "eventos_duplicados", "retiros_sin_inscripcion",
                          "eventos_secciones_prueba", "codigos_alumno_sucios", "fechas_formato_ddmmyyyy",
                          "montos_con_formato_texto", "notas_nsp", "alumnos_versiones_extra"], 0)
    anios = sorted({int(p[:4]) for p in periodos})

    def nuevo_alumno(periodo: str) -> Alumno:
        anio = int(periodo[:4])
        correlativo[anio] += 1
        sede = rng.choice(list(PESO_SEDE), p=list(PESO_SEDE.values()))
        car = rng.choice([c[0] for c in CARRERAS], p=np.array([c[3] for c in CARRERAS]) / 1.0)
        turno = rng.choice(["M", "T", "N"], p=[0.50, 0.20, 0.30])
        trabaja = turno == "N" or (turno == "T" and rng.random() < 0.3)
        edad = rng.integers(22, 32) if trabaja and rng.random() < 0.6 else rng.integers(16, 20)
        nac = date(anio - int(edad), 1, 1) + timedelta(days=int(rng.integers(0, 365)))
        riesgo = float(rng.beta(1.1, 9.0)) + (0.05 if anio >= 2026 else 0.0)
        mod = rng.choice(["Examen de admisión", "Centro preuniversitario", "Primeros puestos",
                          "Traslado externo", "Admisión adulto trabajador"],
                         p=[0.52, 0.20, 0.10, 0.08, 0.10] if trabaja else [0.58, 0.24, 0.12, 0.06, 0.0])
        rend = float(rng.normal(0.35 if mod == "Primeros puestos" else 0.0, 1.0))
        return Alumno(
            codigo=f"U{anio}{correlativo[anio]:05d}", carrera=str(car), sede=str(sede), cohorte=periodo,
            turno=str(turno), trabaja=bool(trabaja), rendimiento=rend, riesgo_pago=min(riesgo, 0.9),
            modalidad_ingreso=str(mod), fecha_nacimiento=nac, genero=str(rng.choice(["F", "M"], p=[0.53, 0.47])),
            distrito=str(rng.choice(DISTRITOS[sede])),
        )

    id_evento = 0
    # en exports chicos se sube la probabilidad para que igual haya casos que detectar
    p_tope = min(0.05, 0.004 / min(1.0, escala))
    for ip, periodo in enumerate(periodos):
        c = cal[periodo]
        exporta = periodo in exportados
        anio, sem = int(periodo[:4]), int(periodo[-1])
        cerrado = c["fin_clases"] < corte
        idx_anio = anio - anios[0]
        # ---- ingresantes del periodo
        base = 1800 * (1.07 ** idx_anio) * (1.0 if sem == 1 else 0.56)
        if periodo == "2026-2":
            base *= 0.86            # caída de admisión 2026-2
        n_ing = int(rng.poisson(base * escala))
        ingresantes = [nuevo_alumno(periodo) for _ in range(n_ing)]
        alumnos.extend(ingresantes)

        # ---- quién se matricula este periodo
        participantes = []
        for a in alumnos:
            if a.egresado or not a.activo:
                continue
            if a.cohorte == periodo:
                if rng.random() < 0.055:      # admitido que nunca se matriculó
                    a.activo = False
                    continue
            elif a.pausa == 1:                # dejó de matricularse este ciclo
                a.pausa = 2
                continue
            elif a.pausa == 2:
                a.pausa = 0
                if rng.random() > 0.40:       # solo 40% vuelve tras dejar un ciclo
                    a.activo = False
                    continue
            participantes.append(a)

        # ---- cursos que pide cada alumno y momento en que se matricula
        solicitudes = []   # (timestamp, alumno, [cursos], canal)
        promedios = [a.ultimo_promedio for a in participantes if a.ultimo_promedio is not None]
        orden_merito = np.sort(np.array(promedios)) if promedios else np.array([])
        for a in participantes:
            pendientes = [(cc, ci) for cc, ci in plan[a.carrera] if cc not in a.aprobados]
            if not pendientes:
                a.egresado = True
                continue
            min_ciclo = min(ci for _, ci in pendientes)
            candidatos = [cc for cc, ci in pendientes if ci <= min_ciclo + 1]
            meta = rng.normal(14, 2) if a.trabaja else rng.normal(21, 2)
            elegidos, cred = [], 0
            for cc in candidatos:
                cr = cursos[cc]["creditos"]
                if cred + cr > min(meta, MAX_CREDITOS):
                    continue
                elegidos.append(cc)
                cred += cr
            if not elegidos:
                elegidos = [candidatos[0]]
            # autorización especial para pasar el tope de créditos (pocos casos)
            if exporta and cred >= 20 and rng.random() < p_tope:
                extra = [cc for cc, _ in pendientes if cc not in elegidos]
                for cc in extra:
                    elegidos.append(cc)
                    cred += cursos[cc]["creditos"]
                    if cred > MAX_CREDITOS:
                        break

            # día de matrícula (0-20 regular, 21-27 extemporánea)
            con_deuda = bool(a.deuda)
            if a.cohorte == periodo or a.ultimo_promedio is None:
                r = rng.random()
                dia = rng.integers(3, 17) if r < 0.45 else rng.integers(17, 21) if r < 0.92 else rng.integers(21, 28)
            elif con_deuda:
                dia = rng.integers(21, 28) if rng.random() < 0.3 else rng.integers(9, 21)
            else:
                pct = np.searchsorted(orden_merito, a.ultimo_promedio) / max(1, len(orden_merito))
                turno_mat = int((1 - pct) * 5)            # 0 = mejores promedios
                r = rng.random()
                if r < 0.04:
                    dia = rng.integers(21, 28)
                elif r < 0.14:
                    dia = rng.integers(17, 21)
                else:
                    dia = turno_mat + (0 if rng.random() < 0.55 else int(rng.geometric(0.3)))
                    dia = min(dia, 20)
            r = rng.random()
            hora = rng.integers(9, 13) if r < 0.3 else rng.integers(14, 19) if r < 0.55 else rng.integers(19, 24)
            if dia == 0 and a.cohorte != periodo and rng.random() < 0.5:
                hora = 8                                   # apertura del sistema
            if dia == 27:
                hora = min(hora, 22)                       # el sistema cierra a las 23:59 del último día
            ts = datetime.combine(c["inicio_matricula"], datetime.min.time()) + timedelta(
                days=int(dia), hours=int(hora), minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60)))
            extemp = dia >= 21
            p_app = {2024: 0.18, 2025: 0.32, 2026: 0.46}.get(anio, 0.1)
            r = rng.random()
            canal = "Presencial" if r < (0.35 if extemp else 0.03) else "App" if rng.random() < p_app else "Web"
            # quien tenía deuda la paga justo antes de matricularse
            for (pp, cuota, monto, venc) in a.deuda:
                if exporta and pp in exportados:
                    pagos.append([a.codigo, pp, cuota, venc, ts - timedelta(hours=int(rng.integers(2, 72))), monto])
            a.deuda = []
            solicitudes.append((ts, a, elegidos, canal))

        solicitudes.sort(key=lambda s: s[0])

        # ---- secciones planificadas (según demanda esperada, con error de planificación)
        vshare = 0.05 + 0.035 * ip if exporta else 0.0
        oferta = {}   # (curso, sede, turno) -> lista de [seccion_id, vacantes, inscritos]
        if exporta:
            demanda = defaultdict(int)
            for _, a, elegidos, _ in solicitudes:
                for cc in elegidos:
                    demanda[(cc, a.sede, a.turno)] += 1
            por_curso = defaultdict(int)
            for (cc, s, t), n in demanda.items():
                por_curso[cc] += n
            factor = {"M": (0.70, 0.98), "T": (0.85, 1.15), "N": (0.95, 1.35)}
            for (cc, s, t), n in sorted(demanda.items()):
                if n < 15 * min(1.0, escala):     # con menos demanda no se abre la sección
                    continue
                k = max(1, round(n * (1 - 0.6 * vshare) * rng.uniform(*factor[t]) / VACANTES["Presencial"]))
                oferta[(cc, s, t)] = [[f"{periodo}-{cc}-{s}{t}{i + 1:02d}", VACANTES["Presencial"], 0]
                                      for i in range(k)]
                for sid, vac, _ in oferta[(cc, s, t)]:
                    secciones.append([sid, periodo, cc, s, t, "Presencial", vac])
            for cc, n in sorted(por_curso.items()):
                k = round(n * vshare * 1.15 / VACANTES["Virtual"])
                if k:
                    oferta[(cc, "VIR", "N")] = [[f"{periodo}-{cc}-VIR{i + 1:02d}", VACANTES["Virtual"], 0]
                                                for i in range(k)]
                    for sid, vac, _ in oferta[(cc, "VIR", "N")]:
                        secciones.append([sid, periodo, cc, "VIR", "N", "Virtual", vac])

        def asignar(a: Alumno, cc: str, excluir: str | None = None):
            orden_t = {"M": "MTN", "T": "TMN", "N": "NTM"}[a.turno]
            opciones = [(cc, a.sede, t) for t in orden_t]
            opciones.insert(0 if rng.random() < vshare * 1.1 else 3, (cc, "VIR", "N"))
            for clave in opciones:
                for sec in oferta.get(clave, []):
                    if sec[0] != excluir and sec[2] < sec[1]:
                        sec[2] += 1
                        return sec[0]
            return None

        # ---- inscripciones, cambios, retiros, notas y pagos
        fin_periodo = []   # (alumno, promedio, cuotas impagas al cierre, abandono)
        for ts, a, elegidos, canal in solicitudes:
            a.matriculado_alguna_vez = True
            t = ts
            inscritos = []
            for cc in elegidos:
                sid = asignar(a, cc) if exporta else f"{periodo}-{cc}"
                if sid is None:
                    continue
                inscritos.append((cc, sid))
                if exporta:
                    id_evento += 1
                    eventos.append([id_evento, a.codigo, sid, "INS", t, canal])
                t += timedelta(seconds=int(rng.integers(4, 40)))
            if not inscritos:
                continue
            if exporta and sum(cursos[cc]["creditos"] for cc, _ in inscritos) > MAX_CREDITOS:
                anom["matriculas_sobre_tope_creditos"] += 1
            # cambio de sección en la misma ventana de matrícula
            if exporta and ts.date() < c["inicio_clases"] - timedelta(days=2):
                for i, (cc, sid) in enumerate(inscritos):
                    if rng.random() < 0.03:
                        nuevo = asignar(a, cc, excluir=sid)
                        if nuevo:
                            tc = ts + timedelta(days=int(rng.integers(1, 3)), minutes=int(rng.integers(1, 600)))
                            id_evento += 1
                            eventos.append([id_evento, a.codigo, sid, "RET", tc, "Web"])
                            id_evento += 1
                            eventos.append([id_evento, a.codigo, nuevo, "INS", tc + timedelta(seconds=25), "Web"])
                            inscritos[i] = (cc, nuevo)

            # abandono del ciclo: retira todo entre la semana 3 y 8
            abandona = rng.random() < (0.015 + 0.05 * (a.rendimiento < -1) + 0.02 * a.trabaja
                                       + 0.03 * (a.riesgo_pago > 0.35))
            suma, creds, nsp_ciclo = 0.0, 0, 0
            for cc, sid in inscritos:
                cur = cursos[cc]
                p_ret = 0.022 + 0.05 * (a.rendimiento < -0.8) + 0.03 * (cur["dificultad"] < -2) + 0.015 * a.trabaja
                retira = abandona or rng.random() < p_ret
                if retira:
                    fr = datetime.combine(c["inicio_clases"], datetime.min.time()) + timedelta(
                        days=int(rng.integers(14, 57)), hours=int(rng.integers(8, 23)), minutes=int(rng.integers(0, 60)))
                    if exporta and fr.date() <= corte:
                        id_evento += 1
                        eventos.append([id_evento, a.codigo, sid, "RET", fr, "Web" if rng.random() < 0.7 else "App"])
                    if fr.date() <= corte or not exporta:
                        continue
                if not cerrado:
                    continue
                nsp = rng.random() < (0.012 + 0.02 * a.trabaja)
                nota = 0 if nsp else int(np.clip(round(
                    12.6 + 2.4 * a.rendimiento + cur["dificultad"] - 0.7 * a.trabaja + rng.normal(0, 2.3)), 0, 20))
                if nota >= 11:
                    a.aprobados.add(cc)
                suma += nota * cur["creditos"]
                creds += cur["creditos"]
                nsp_ciclo += nsp
                if exporta:
                    notas.append([a.codigo, sid, "NSP" if nsp else str(nota)])
            promedio = suma / creds if creds else None

            # pagos: matrícula al momento de matricularse + 5 pensiones
            car = car_info[a.carrera]
            pension = car[4] * (0.8 if a.sede == "AQ" else 1.0) * (1.05 ** max(0, anio - 2024))
            if exporta:
                pagos.append([a.codigo, periodo, 0, ts.date(), ts + timedelta(minutes=int(rng.integers(1, 30))),
                              CUOTA_MATRICULA])
            impagas = []
            for k in range(1, 6):
                venc = c["inicio_clases"] + timedelta(days=7 + 26 * (k - 1))
                monto = round(pension, 2)
                if abandona and k >= 3:
                    fp = None
                elif rng.random() < 1 - a.riesgo_pago * 1.3:
                    fp = datetime.combine(venc, datetime.min.time()) - timedelta(
                        days=int(rng.integers(0, 6)), hours=int(rng.integers(-12, 10)))
                elif rng.random() < 0.65:
                    fp = datetime.combine(venc, datetime.min.time()) + timedelta(
                        days=int(rng.exponential(22)) + 1, hours=int(rng.integers(8, 20)))
                else:
                    fp = None
                if fp is not None and fp.date() > c["fin_clases"]:
                    fp = None                                       # se paga recién al volver
                if fp is None:
                    impagas.append((periodo, k, monto, venc))
                if exporta:
                    pagado = fp is not None and fp.date() <= corte
                    pagos.append([a.codigo, periodo, k, venc, fp if pagado else None, monto])
            fin_periodo.append((a, promedio, impagas, abandona))

        # ---- quién sigue el próximo ciclo
        if not cerrado:
            continue
        for a, promedio, impagas, abandona in fin_periodo:
            a.deuda = impagas
            a.ultimo_promedio = promedio if promedio is not None else 0.0
            if all(cc in a.aprobados for cc, _ in plan[a.carrera]):
                a.egresado = True
                continue
            prom = a.ultimo_promedio
            logit = (3.1 + 0.30 * (prom - 12.5) - 0.55 * len(impagas) - 0.25 * a.trabaja
                     - 0.95 * (a.cohorte == periodo) - 2.5 * abandona - 0.25 * (anio >= 2026))
            if rng.random() > sigmoide(logit):
                a.pausa = 1

    # ----------------------------------------------------------------------
    # Exportar con los problemas típicos del sistema
    # ----------------------------------------------------------------------
    ev = pd.DataFrame(eventos, columns=["id_evento", "codigo_alumno", "seccion_id", "tipo", "fecha_hora", "canal"])

    # doble clic
    ins = ev.index[ev["tipo"] == "INS"]
    dup_idx = rng.choice(ins, size=int(len(ins) * 0.012), replace=False)
    dups = ev.loc[dup_idx].copy()
    dups["fecha_hora"] = dups["fecha_hora"] + pd.to_timedelta(rng.integers(0, 4, len(dups)), unit="s")
    anom["eventos_duplicados"] = len(dups)

    # retiros huérfanos: retiros de secciones donde el alumno no se inscribió
    sec_df = pd.DataFrame(secciones, columns=["seccion_id", "periodo", "curso_cod", "sede", "turno", "modalidad",
                                              "vacantes"])
    pares = set(zip(ev["codigo_alumno"], ev["seccion_id"]))
    huerf = []
    n_huerf = max(3, int(60 * escala))
    while len(huerf) < n_huerf:
        fila = ev.iloc[int(rng.integers(len(ev)))]
        sec = sec_df.iloc[int(rng.integers(len(sec_df)))]
        if (fila["codigo_alumno"], sec["seccion_id"]) in pares:
            continue
        ini = cal[sec["periodo"]]["inicio_clases"]
        huerf.append([0, fila["codigo_alumno"], sec["seccion_id"], "RET",
                      datetime.combine(ini, datetime.min.time()) + timedelta(days=int(rng.integers(10, 40)), hours=10),
                      "Presencial"])
    anom["retiros_sin_inscripcion"] = len(huerf)

    # eventos de prueba del área de sistemas
    prueba = []
    for p in exportados:
        for _ in range(int(rng.integers(15, 35))):
            prueba.append([0, "U000000000", f"PRB-{p}-{int(rng.integers(1, 9)):02d}",
                           str(rng.choice(["INS", "RET"])),
                           datetime.combine(cal[p]["inicio_matricula"], datetime.min.time())
                           - timedelta(days=int(rng.integers(1, 6)), hours=int(rng.integers(0, 10))), "Web"])
    anom["eventos_secciones_prueba"] = len(prueba)

    ev = pd.concat([ev, dups, pd.DataFrame(huerf, columns=ev.columns), pd.DataFrame(prueba, columns=ev.columns)],
                   ignore_index=True)
    ev = ev.sort_values(["fecha_hora", "id_evento"], kind="stable").reset_index(drop=True)
    ev["id_evento"] = np.arange(1, len(ev) + 1) + 100000

    # códigos sucios
    sucios = rng.random(len(ev)) < 0.02
    sucios &= ev["codigo_alumno"].ne("U000000000").to_numpy()
    cods = ev["codigo_alumno"].to_numpy(dtype=object)
    for i in np.flatnonzero(sucios):
        cods[i] = cods[i].lower() if rng.random() < 0.5 else f" {cods[i]} "
    ev["codigo_alumno"] = cods
    anom["codigos_alumno_sucios"] = int(sucios.sum())

    # fechas: ventanilla graba dd/mm/yyyy hh:mm
    vent = ev["canal"].eq("Presencial").to_numpy()
    ev["fecha_hora"] = np.where(vent, ev["fecha_hora"].dt.strftime("%d/%m/%Y %H:%M"),
                                ev["fecha_hora"].dt.strftime("%Y-%m-%d %H:%M:%S"))
    anom["fechas_formato_ddmmyyyy"] = int(vent.sum())
    ev.to_csv(salida / "eventos_matricula.csv", index=False)

    # secciones (turno con el código del sistema, sede como código)
    sec_df.to_csv(salida / "secciones.csv", index=False)

    # pagos: algunos montos como texto
    pg = pd.DataFrame(pagos, columns=["codigo_alumno", "periodo", "cuota", "fecha_vencimiento", "fecha_pago", "monto"])
    pg = pg.drop_duplicates(["codigo_alumno", "periodo", "cuota"], keep="last")
    pg["fecha_pago"] = pd.to_datetime(pg["fecha_pago"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    texto = rng.random(len(pg)) < 0.05
    pg["monto"] = [f"S/ {m:,.2f}" if t else f"{m:.2f}" for m, t in zip(pg["monto"], texto)]
    anom["montos_con_formato_texto"] = int(texto.sum())
    pg.sort_values(["periodo", "codigo_alumno", "cuota"]).to_csv(salida / "pagos.csv", index=False)

    nt = pd.DataFrame(notas, columns=["codigo_alumno", "seccion_id", "nota_final"])
    anom["notas_nsp"] = int((nt["nota_final"] == "NSP").sum())
    nt.to_csv(salida / "notas.csv", index=False)

    # maestro de alumnos: los que aparecen en la ventana exportada
    vistos = {cod.strip().upper() for cod in ev["codigo_alumno"]}
    filas = []
    variantes_sede = {"LN": ["Lima Norte", "LIMA NORTE", "lima norte ", "Lima  Norte"],
                      "LC": ["Lima Centro", "LIMA CENTRO", " Lima Centro"],
                      "AQ": ["Arequipa", "AREQUIPA", "arequipa"]}
    for a in alumnos:
        if a.codigo not in vistos and a.cohorte < PRIMER_PERIODO_EXPORTADO:
            continue
        sede_txt = variantes_sede[a.sede][0] if rng.random() < 0.85 else str(rng.choice(variantes_sede[a.sede]))
        act = datetime.combine(cal[a.cohorte]["inicio_matricula"], datetime.min.time()) - timedelta(days=20)
        fila = [a.codigo, a.carrera, sede_txt, a.cohorte, a.modalidad_ingreso, a.fecha_nacimiento, a.genero,
                a.distrito, act]
        filas.append(fila)
        if rng.random() < 0.03:     # versión más reciente con cambio de distrito
            nueva = list(fila)
            nueva[7] = str(rng.choice(DISTRITOS[a.sede]))
            nueva[8] = min(act + timedelta(days=int(rng.integers(60, 700))),
                           datetime.combine(corte, datetime.min.time()))
            filas.append(nueva)
            anom["alumnos_versiones_extra"] += 1
    al = pd.DataFrame(filas, columns=["codigo_alumno", "carrera_cod", "sede", "periodo_ingreso",
                                      "modalidad_ingreso", "fecha_nacimiento", "genero", "distrito",
                                      "fecha_actualizacion"])
    al.sample(frac=1, random_state=seed).to_csv(salida / "alumnos.csv", index=False)

    pd.DataFrame([dict(carrera_cod=c[0], carrera=c[1], facultad=c[2]) for c in CARRERAS]).to_csv(
        salida / "carreras.csv", index=False)
    pd.DataFrame([{k: v for k, v in cur.items() if k != "dificultad"} for cur in cursos.values()]).to_csv(
        salida / "cursos.csv", index=False)
    pd.DataFrame([dict(carrera_cod=car, curso_cod=cc, ciclo=ci) for car, p in plan.items() for cc, ci in p]).to_csv(
        salida / "plan_estudios.csv", index=False)

    meta = dict(seed=seed, escala=escala, corte=corte.isoformat(), periodos=exportados, anomalias=dict(anom))
    (salida / "_anomalias.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return salida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=SALIDA_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--corte", type=date.fromisoformat, default=CORTE_DEFECTO)
    args = ap.parse_args()
    ruta = generar(args.salida, args.escala, args.seed, args.corte)
    meta = json.loads((ruta / "_anomalias.json").read_text(encoding="utf-8"))
    print(f"Exports generados en {ruta} (corte {meta['corte']})")
    for f in sorted(ruta.glob("*.csv")):
        n = sum(1 for _ in open(f, encoding="utf-8")) - 1
        print(f"  {f.name:<24} {n:>9,} filas")
    print("Anomalías inyectadas:")
    for k, v in meta["anomalias"].items():
        print(f"  {k:<32} {v:>6,}")


if __name__ == "__main__":
    main()
