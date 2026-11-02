"""
Genera el corpus normativo de la Universidad Qhapaq Ñan (ficticia) y el set de
preguntas para evaluar la búsqueda.

    python datos/generar_corpus.py            # datos/corpus/*.md y datos/preguntas.json

Todo es sintético. Montos, plazos y porcentajes salen de la semilla, así que
el texto de los artículos y las respuestas esperadas cambian juntos.

Lo que lo hace parecido a un corpus real:
- los documentos vienen de PDF: pie de página repetido y palabras cortadas
  con guion al final de línea;
- una resolución de 2026 modifica cinco artículos del reglamento de estudios e
  incorpora uno nuevo; el texto antiguo sigue en el reglamento original;
- el reglamento dice "asignatura", "desaprobar" y "reserva de matrícula"; los
  alumnos preguntan por "curso", "jalar" y "congelar";
- hay preguntas que el corpus no responde, varias con palabras que sí aparecen
  en los reglamentos (prácticas, verano, carrera).
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).parent
UNIVERSIDAD = "Universidad Qhapaq Ñan"
PIE = f"{UNIVERSIDAD} — Secretaría General | Pág. {{pag}}"


@dataclass
class Articulo:
    num: str
    titulo: str
    texto: str
    formal: list[str] = field(default_factory=list)
    coloquial: list[str] = field(default_factory=list)
    dato: str = ""


@dataclass
class Documento:
    codigo: str
    titulo: str
    aprobado: str
    vigente_desde: str
    capitulos: list[tuple[str, list[Articulo]]]
    tipo: str = "reglamento"


def parametros(rng: random.Random) -> dict:
    """Cifras que cambian con la semilla."""
    return {
        "recargo": rng.choice([80, 90, 100, 120]),
        "costo_sust": rng.choice([60, 70, 80]),
        "costo_rezagado": rng.choice([50, 60, 70]),
        "carga_tercera": rng.choice([15, 16, 18]),
        "horas_practicas": rng.choice([480, 520, 600]),
        "creditos_egreso": rng.choice([200, 210, 220]),
        "creditos_max": rng.choice([22, 23]),
        "mora_dia": rng.choice(["1.50", "2.00", "2.50"]),
        "mora_tope": rng.choice([40, 45, 50]),
        "fracc_cuotas": rng.choice([4, 5, 6]),
        "pronto_pago": rng.choice([4, 5, 6]),
        "hermanos": rng.choice([10, 15]),
        "devolucion": rng.choice([70, 75, 80]),
        "credito_adicional": rng.choice([180, 195, 210]),
        "certificado": rng.choice([120, 135, 150]),
        "constancia": rng.choice([25, 30, 35]),
        "similitud": rng.choice([15, 20, 25]),
        "costo_bachiller": rng.choice([650, 700, 750]),
        "costo_titulo": rng.choice([850, 950, 1050]),
        "dias_diploma": rng.choice([30, 45]),
        "promedio_beca": rng.choice([13, 14]),
        "sesiones_psico": rng.choice([6, 8]),
    }


def reglamento_estudios(p: dict) -> Documento:
    A = Articulo
    caps = [
        ("CAPÍTULO I: DISPOSICIONES GENERALES", [
            A("1", "Objeto",
              "El presente reglamento norma los procesos académicos de los estudiantes de pregrado de la "
              f"{UNIVERSIDAD}: matrícula, evaluación, promoción, traslados y egreso."),
            A("2", "Ámbito",
              "Es de cumplimiento obligatorio para estudiantes, docentes y personal administrativo de todas "
              "las facultades y sedes."),
            A("3", "Año académico",
              "El año académico comprende dos semestres regulares de 16 semanas cada uno, incluida la semana "
              "de exámenes finales, y un periodo de verano opcional de 8 semanas.",
              ["¿Cuántas semanas dura un semestre regular?"],
              ["cuantas semanas dura el ciclo normal?", "el ciclo cuantas semanas tiene?"],
              "16 semanas"),
            A("4", "Crédito académico",
              "Un crédito académico equivale a 16 horas de teoría o a 32 horas de práctica durante el "
              "semestre.",
              ["¿A cuántas horas de clase equivale un crédito académico?"],
              ["un credito cuantas horas de clase son?"],
              "16 horas"),
        ]),
        ("CAPÍTULO II: DE LA MATRÍCULA", [
            A("5", "Matrícula regular",
              "La matrícula se realiza en la intranet dentro de las fechas del calendario académico. Para "
              "matricularse, el estudiante no debe tener deudas vencidas con la universidad ni sanción "
              "disciplinaria vigente.",
              ["¿Qué requisitos debo cumplir para matricularme en el semestre?"],
              ["que necesito para poder matricularme?", "me puedo matricular si tengo una sancion?"],
              "deudas vencidas"),
            A("6", "Créditos por semestre",
              f"El estudiante se matricula en un mínimo de 12 y un máximo de {p['creditos_max']} créditos por "
              "semestre. Los estudiantes del tercio superior pueden matricularse hasta en 26 créditos.",
              ["¿Cuál es el número máximo de créditos en que puedo matricularme?"],
              ["cuantos creditos como maximo puedo llevar en el ciclo?",
               "puedo llevar mas creditos si estoy en el tercio?"],
              f"{p['creditos_max'] + 2} créditos"),
            A("7", "Matrícula extemporánea",
              "Concluido el plazo regular, la matrícula extemporánea procede hasta el último día hábil de la "
              f"segunda semana de clases, previo pago de un recargo de S/ {p['recargo']}.",
              ["¿Hasta cuándo se puede realizar la matrícula extemporánea?"],
              ["me olvide de matricularme, todavia puedo?", "se me paso la fecha de matricula, que hago?"],
              f"S/ {p['recargo']}"),
            A("8", "Cambio de sección",
              "El cambio de sección o de horario se solicita en la intranet durante la primera semana de "
              "clases y está sujeto a la disponibilidad de vacantes.",
              ["¿Hasta cuándo puedo solicitar el cambio de sección?"],
              ["me quiero cambiar de horario porque se me cruza con el trabajo, hasta cuando puedo?"],
              "primera semana"),
            A("9", "Prerrequisitos",
              "No procede la matrícula en una asignatura sin haber aprobado sus prerrequisitos según el plan "
              "de estudios. El sistema bloquea automáticamente la inscripción.",
              ["¿Puedo matricularme en una asignatura sin haber aprobado su prerrequisito?"],
              ["puedo llevar calculo 2 si jale calculo 1?", "me dejan llevar un curso sin el prerequisito?"],
              "prerrequisitos"),
            A("10", "Retiro de asignatura",
              "El estudiante puede retirarse de una o más asignaturas hasta la semana 10 del semestre. La "
              "asignatura retirada no se considera desaprobada ni cuenta como matrícula para efectos del "
              "artículo 24.° No hay devolución de pagos.",
              ["¿Hasta qué semana puedo retirarme de una asignatura?"],
              ["hasta cuando me puedo retirar de un curso que voy jalando?",
               "hasta que semana puedo dejar un curso sin que me cuente?"],
              "semana 8"),
            A("11", "Retiro del semestre",
              "El retiro de todas las asignaturas del semestre se solicita hasta la semana 12. Los pagos se "
              "rigen por el Reglamento de Pagos y Pensiones.",
              ["¿Hasta qué semana puedo retirarme de todo el semestre?"],
              ["quiero dejar todos mis cursos este ciclo, hasta cuando puedo?"],
              "semana 12"),
            A("12", "Reserva de matrícula",
              "El estudiante puede reservar su matrícula hasta por cuatro semestres académicos, consecutivos o "
              "no, durante toda su permanencia. La solicitud se presenta antes del inicio de clases.",
              ["¿Por cuántos semestres puedo reservar mi matrícula?"],
              ["quiero congelar un ciclo para chambear, por cuanto tiempo puedo?",
               "puedo congelar la carrera un tiempo?"],
              "cuatro semestres"),
            A("13", "Reincorporación",
              "El estudiante que dejó de estudiar solicita su reincorporación hasta 30 días antes del inicio "
              "del semestre. Se reincorpora al plan de estudios vigente y se le convalidan las asignaturas "
              "aprobadas que correspondan.",
              ["¿Con qué plan de estudios continúa un estudiante que se reincorpora?"],
              ["vuelvo despues de dos años, con que malla sigo?"],
              "plan de estudios vigente"),
        ]),
        ("CAPÍTULO III: DE LA EVALUACIÓN", [
            A("14", "Sistema de calificación",
              "La calificación es vigesimal, de cero (00) a veinte (20). La nota mínima aprobatoria es once "
              "(11). En el promedio final de la asignatura la fracción igual o mayor a 0.5 se redondea al "
              "entero superior; las notas parciales no se redondean.",
              ["¿Cuál es la nota mínima aprobatoria?", "¿Se redondea un promedio final de 10.5?"],
              ["con cuanto se pasa un curso?", "si saco 10.5 de promedio apruebo?"],
              "once (11)"),
            A("15", "Evaluación continua",
              "El sílabo de cada asignatura fija las evaluaciones y sus pesos. El examen parcial y el examen "
              "final no pueden pesar más de 30% cada uno.",
              ["¿Cuánto puede pesar como máximo el examen final en la nota?"],
              ["cuanto vale el final en la nota del curso?"],
              "30%"),
            A("16", "Rectificación de notas",
              "El estudiante puede solicitar la rectificación de una calificación dentro de los tres días "
              "hábiles siguientes a su publicación, mediante la intranet y ante el docente. En segunda "
              "instancia resuelve el director de carrera.",
              ["¿Cuál es el plazo para solicitar la rectificación de una nota?"],
              ["me pusieron mal la nota del parcial, hasta cuando puedo reclamar?",
               "el profe se equivoco en mi nota, donde reclamo?"],
              "tres días hábiles"),
            A("17", "Examen sustitutorio",
              "El examen sustitutorio reemplaza la nota más baja entre el examen parcial y el examen final. "
              "Pueden rendirlo los estudiantes con promedio de la asignatura igual o mayor a siete (07), "
              f"previo pago de S/ {p['costo_sust']}.",
              ["¿Qué nota reemplaza el examen sustitutorio?"],
              ["si doy el sustitutorio que nota me reemplazan?", "el sustitutorio reemplaza el parcial o el final?"],
              "examen final"),
            A("18", "Asistencia",
              "La asistencia a clases es obligatoria. El estudiante que acumula más de 30% de inasistencias "
              "queda inhabilitado por inasistencia (IPI) y obtiene nota cero (00) en la asignatura.",
              ["¿Cuál es el porcentaje máximo de inasistencias permitido?"],
              ["cuantas faltas puedo tener sin que me inhabiliten?", "con cuantas faltas me jalan por IPI?"],
              "25%"),
            A("19", "Justificación de inasistencias",
              "Las inasistencias por enfermedad se justifican con certificado médico presentado dentro de los "
              "cinco días hábiles siguientes. La justificación permite rendir evaluaciones pendientes, pero no "
              "anula la inasistencia para el cálculo del límite del artículo 18.°",
              ["¿En qué plazo debo justificar una inasistencia por enfermedad?"],
              ["falte por estar enfermo, hasta cuando presento el certificado?"],
              "cinco días hábiles"),
            A("20", "Evaluación rezagada",
              "Quien no rinde el examen parcial o final por causa justificada puede solicitar evaluación "
              "rezagada dentro de los tres días hábiles siguientes, previo pago de "
              f"S/ {p['costo_rezagado']}.",
              ["¿Cuánto cuesta rendir un examen rezagado?"],
              ["no pude dar el parcial, puedo darlo otro dia? cuanto cuesta?"],
              f"S/ {p['costo_rezagado']}"),
            A("21", "Promedio ponderado",
              "El promedio ponderado se obtiene multiplicando la nota final de cada asignatura por sus "
              "créditos y dividiendo la suma entre el total de créditos matriculados. Incluye las asignaturas "
              "desaprobadas y excluye las retiradas.",
              ["¿Cómo se calcula el promedio ponderado?"],
              ["los cursos jalados cuentan en mi ponderado?"],
              "créditos"),
            A("22", "Orden de mérito",
              "Al cierre de cada semestre se publica el orden de mérito por carrera y promoción: quinto, "
              "tercio y medio superior. Solo se consideran estudiantes con al menos 12 créditos aprobados en "
              "el semestre.",
              ["¿Qué requisito hay para figurar en el orden de mérito?"],
              ["como entro al tercio superior?", "cuantos creditos tengo que aprobar para salir en el tercio?"],
              "12 créditos aprobados"),
        ]),
        ("CAPÍTULO IV: DE LA PERMANENCIA", [
            A("23", "Segunda matrícula",
              "El estudiante que desaprueba una asignatura debe matricularse en ella en el semestre siguiente "
              "en que se dicte.",
              ["¿Cuándo debo volver a matricularme en una asignatura desaprobada?"],
              ["si jalo un curso tengo que llevarlo de nuevo el siguiente ciclo?"],
              "semestre siguiente"),
            A("24", "Tercera matrícula",
              "El estudiante que se matricula por tercera vez en una asignatura puede llevar como máximo "
              f"{p['carga_tercera']} créditos en ese semestre y recibe tutoría obligatoria.",
              ["¿Cuántos créditos puede llevar un estudiante con una asignatura en tercera matrícula?"],
              ["me toca llevar un curso por trica, cuantos creditos puedo llevar?",
               "voy por mi tercera vez en un curso, me limitan los creditos?"],
              f"{p['carga_tercera']} créditos"),
            A("25", "Cuarta desaprobación",
              "El estudiante que desaprueba una misma asignatura por cuarta vez es separado definitivamente "
              "de la universidad.",
              ["¿Qué ocurre si un estudiante desaprueba una asignatura por cuarta vez?"],
              ["si jalo un curso por cuarta vez me botan?"],
              "dos semestres"),
            A("26", "Bajo rendimiento",
              "El estudiante con promedio ponderado semestral menor a 10.5 en dos semestres consecutivos "
              "queda en matrícula condicionada: lleva como máximo 16 créditos y firma un compromiso "
              "académico.",
              ["¿Qué es la matrícula condicionada por bajo rendimiento?"],
              ["me fue mal dos ciclos seguidos, me limitan algo?"],
              "10.5"),
        ]),
        ("CAPÍTULO V: DE LAS CONVALIDACIONES Y TRASLADOS", [
            A("27", "Convalidación",
              "Se convalidan asignaturas aprobadas en otras universidades licenciadas cuando el contenido "
              "coincide al menos en 75% con el sílabo de la asignatura. La solicitud se presenta en el primer "
              "semestre de estudios.",
              ["¿Qué requisito debe cumplir una asignatura para ser convalidada?"],
              ["vengo de otra universidad, me reconocen los cursos que ya aprobe?"],
              "75%"),
            A("28", "Traslado interno",
              "El cambio de carrera procede una sola vez, con al menos 24 créditos aprobados y promedio "
              "ponderado acumulado mínimo de 12.",
              ["¿Qué requisitos tiene el traslado interno a otra carrera?"],
              ["me quiero cambiar de carrera, que necesito?"],
              "24 créditos"),
            A("29", "Traslado externo",
              "Los estudiantes de otras universidades pueden trasladarse si han aprobado al menos dos "
              "semestres o 36 créditos y no tienen sanción disciplinaria en su universidad de origen.",
              ["¿Cuántos créditos necesita un estudiante de otra universidad para trasladarse?"],
              ["estudio en otra u y me quiero pasar aca, que piden?"],
              "36 créditos"),
        ]),
        ("CAPÍTULO VI: DEL EGRESO", [
            A("30", "Prácticas preprofesionales",
              "Las prácticas preprofesionales son obligatorias. Se inician con 140 créditos aprobados y "
              f"suman como mínimo {p['horas_practicas']} horas, acreditadas con convenio y constancia de la "
              "empresa.",
              ["¿Cuántas horas de prácticas preprofesionales son obligatorias?"],
              ["cuantas horas de practicas necesito para egresar?",
               "desde cuantos creditos puedo empezar mis practicas?"],
              f"{p['horas_practicas']} horas"),
            A("31", "Periodo de verano",
              "En el periodo de verano el estudiante puede matricularse como máximo en dos asignaturas y 11 "
              "créditos.",
              ["¿Cuántas asignaturas se pueden llevar en el periodo de verano?"],
              ["cuantos cursos puedo llevar en verano?"],
              "dos asignaturas"),
            A("32", "Asignatura dirigida",
              "Cuando a un estudiante le faltan hasta dos asignaturas para egresar y estas no se dictan en el "
              "semestre, puede solicitar llevarlas en modalidad dirigida con un docente asignado.",
              ["¿Qué es una asignatura dirigida y quién puede solicitarla?"],
              ["me falta un solo curso para terminar y no lo abren, que hago?"],
              "dos asignaturas"),
            A("33", "Egreso",
              f"Es egresado quien aprueba los {p['creditos_egreso']} créditos del plan de estudios y acredita "
              "las prácticas preprofesionales.",
              ["¿Cuántos créditos se necesitan para egresar?"],
              ["cuantos creditos tengo que tener para ser egresado?"],
              f"{p['creditos_egreso']} créditos"),
        ]),
        ("CAPÍTULO VII: DE LA INTEGRIDAD ACADÉMICA", [
            A("34", "Integridad académica",
              "Constituyen faltas contra la integridad académica el plagio, la copia en evaluaciones, la "
              "suplantación y la presentación de trabajos ajenos como propios.",
              ["¿Qué conductas se consideran faltas contra la integridad académica?"],
              ["presentar el trabajo de otro cuenta como falta?"],
              "plagio"),
            A("35", "Consecuencia académica del plagio",
              "Sin perjuicio del proceso disciplinario, la evaluación en la que se comprueba plagio o copia se "
              "califica con nota cero (00).",
              ["¿Qué nota recibe una evaluación en la que se comprueba plagio?"],
              ["que pasa si me chapan copiando en el examen?"],
              "cero (00)"),
        ]),
    ]
    return Documento("RE-2024", "Reglamento de Estudios de Pregrado", "2024-01-15", "2024-03-01", caps)


def resolucion_2026(p: dict) -> tuple[Documento, list[Articulo]]:
    """Resolución que modifica el RE-2024. Devuelve el documento y los artículos nuevos."""
    nuevos = [
        Articulo("6", "Créditos por semestre",
                 f"El estudiante se matricula en un mínimo de 12 y un máximo de {p['creditos_max'] + 2} créditos "
                 "por semestre. Los estudiantes del tercio superior pueden matricularse hasta en 26 créditos."),
        Articulo("10", "Retiro de asignatura",
                 "El estudiante puede retirarse de una o más asignaturas hasta la semana 8 del semestre. La "
                 "asignatura retirada no se considera desaprobada ni cuenta como matrícula para efectos del "
                 "artículo 24.° No hay devolución de pagos."),
        Articulo("17", "Examen sustitutorio",
                 "El examen sustitutorio reemplaza únicamente la nota del examen final. Pueden rendirlo los "
                 "estudiantes con promedio de la asignatura igual o mayor a ocho (08), previo pago de "
                 f"S/ {p['costo_sust']}."),
        Articulo("18", "Asistencia",
                 "La asistencia a clases es obligatoria, presencial o virtual. El estudiante que acumula más de "
                 "25% de inasistencias queda inhabilitado por inasistencia (IPI) y obtiene nota cero (00) en la "
                 "asignatura."),
        Articulo("25", "Cuarta desaprobación",
                 "El estudiante que desaprueba una misma asignatura por cuarta vez es suspendido por dos "
                 "semestres. Al reincorporarse lleva la asignatura con tutoría obligatoria; si la desaprueba "
                 "por quinta vez es separado definitivamente."),
        Articulo("35-A", "Uso de inteligencia artificial generativa",
                 "El uso de herramientas de inteligencia artificial generativa en trabajos y evaluaciones solo "
                 "está permitido cuando el sílabo lo autoriza, y el estudiante debe declarar la herramienta y "
                 "el uso que le dio. El uso no autorizado o no declarado es una falta contra la integridad "
                 "académica.",
                 ["¿Está permitido usar herramientas de inteligencia artificial en los trabajos?"],
                 ["puedo usar chatgpt para hacer mis trabajos?", "me pueden sancionar por usar IA en una tarea?"],
                 "declarar"),
    ]
    arts = []
    for i, a in enumerate(nuevos, 1):
        verbo = ("Incorporar el artículo {n}.° al Reglamento de Estudios de Pregrado (RE-2024), con el "
                 "siguiente texto:") if "-" in a.num else (
            "Modificar el artículo {n}.° del Reglamento de Estudios de Pregrado (RE-2024), que queda "
            "redactado de la siguiente manera:")
        arts.append(Articulo(str(i), "", verbo.format(n=a.num) + f" «Artículo {a.num}.° — {a.titulo}. {a.texto}»"))
    arts.append(Articulo(str(len(nuevos) + 1), "",
                         "La presente resolución entra en vigencia el 1 de marzo de 2026."))
    doc = Documento("RCU-014-2026", "Resolución N.° 014-2026-CU", "2026-02-20", "2026-03-01",
                    [("SE RESUELVE:", arts)], tipo="resolucion")
    return doc, nuevos


def reglamento_pagos(p: dict) -> Documento:
    A = Articulo
    caps = [
        ("TÍTULO I: DE LAS PENSIONES", [
            A("1", "Objeto", "Regula las pensiones, cuotas, descuentos y trámites con costo de los estudiantes "
              "de pregrado."),
            A("2", "Escalas de pensión",
              "La pensión se fija en cinco escalas, de la A a la E, según la evaluación socioeconómica que se "
              "realiza al ingresar.",
              ["¿Cómo se asigna la escala de pensión?"],
              ["en que escala estoy y como me la ponen?"], "cinco escalas"),
            A("3", "Recategorización",
              "El estudiante puede solicitar una vez al año el cambio de escala, adjuntando sustento "
              "económico, hasta 30 días antes del inicio del semestre.",
              ["¿Con qué frecuencia puedo solicitar la recategorización de mi escala?"],
              ["puedo pedir que me bajen la escala de pension?"], "una vez al año"),
            A("4", "Cuotas",
              "Cada semestre se paga la matrícula y cinco cuotas mensuales. Cada cuota vence el último día "
              "hábil del mes.",
              ["¿En cuántas cuotas se divide la pensión del semestre?"],
              ["cuantas cuotas se pagan en el ciclo?"], "cinco cuotas"),
            A("5", "Mora",
              f"El pago fuera de fecha genera una mora de S/ {p['mora_dia']} por día de atraso, con un tope de "
              f"S/ {p['mora_tope']} por cuota.",
              ["¿Cuánto es la mora por el pago atrasado de una cuota?"],
              ["si pago tarde la cuota cuanto me cobran de mas?"], f"S/ {p['mora_dia']}"),
            A("6", "Deuda vencida",
              "La deuda vencida no impide rendir evaluaciones del semestre en curso, pero impide matricularse "
              "en el semestre siguiente y emitir certificados y constancias.",
              ["¿Puedo rendir mis exámenes si tengo deuda vencida?"],
              ["si debo pensiones me pueden prohibir dar el examen final?"], "no impide rendir evaluaciones"),
            A("7", "Fraccionamiento",
              f"Las deudas mayores a S/ 1,000 pueden fraccionarse hasta en {p['fracc_cuotas']} cuotas, con una "
              "cuota inicial de 20%.",
              ["¿Es posible fraccionar una deuda con la universidad?"],
              ["puedo pagar mi deuda en partes?"], f"{p['fracc_cuotas']} cuotas"),
        ]),
        ("TÍTULO II: DE LOS DESCUENTOS Y DEVOLUCIONES", [
            A("8", "Pronto pago",
              f"Quien paga el semestre completo antes del inicio de clases recibe un descuento de "
              f"{p['pronto_pago']}% sobre las cuotas.",
              ["¿Existe descuento por pagar el semestre completo por adelantado?"],
              ["hay descuento si pago todo el ciclo adelantado?"], f"{p['pronto_pago']}%"),
            A("9", "Descuento por hermanos",
              f"Cuando dos o más hermanos estudian en la universidad, el segundo y siguientes reciben "
              f"{p['hermanos']}% de descuento en la pensión.",
              ["¿Hay descuento cuando estudian hermanos en la universidad?"],
              ["mi hermano tambien estudia aca, nos hacen descuento?"], f"{p['hermanos']}%"),
            A("10", "Devolución por retiro",
              f"Si el retiro del semestre se solicita hasta la segunda semana de clases se devuelve "
              f"{p['devolucion']}% de lo pagado por cuotas. Después de esa fecha no hay devolución.",
              ["¿Se devuelve lo pagado si me retiro del semestre?"],
              ["si me retiro del ciclo me devuelven la plata?"], f"{p['devolucion']}%"),
            A("11", "Créditos adicionales",
              "Los créditos que excedan el máximo regular del semestre se pagan aparte a razón de "
              f"S/ {p['credito_adicional']} por crédito.",
              ["¿Cuánto se paga por cada crédito adicional?"],
              ["si llevo mas creditos de lo normal pago mas?"], f"S/ {p['credito_adicional']}"),
        ]),
        ("TÍTULO III: DE LOS TRÁMITES", [
            A("12", "Certificados y constancias",
              f"El certificado de estudios cuesta S/ {p['certificado']} y la constancia de matrícula o de "
              f"notas, S/ {p['constancia']}. Se entregan en cinco días hábiles.",
              ["¿Cuál es el costo del certificado de estudios?"],
              ["cuanto cuesta sacar un certificado de estudios?", "cuanto sale una constancia de notas?"],
              f"S/ {p['certificado']}"),
            A("13", "Medios de pago",
              "Los pagos se realizan en bancos y agentes autorizados, en la banca por internet o con billetera "
              "digital usando el código de estudiante. No se recibe efectivo en el campus.",
              ["¿Qué medios de pago acepta la universidad?"],
              ["puedo pagar en efectivo en la caja de la u?"], "No se recibe efectivo"),
        ]),
    ]
    return Documento("RP-2025", "Reglamento de Pagos y Pensiones", "2025-06-30", "2025-08-01", caps)


def reglamento_grados(p: dict) -> Documento:
    A = Articulo
    caps = [
        ("CAPÍTULO I: DEL GRADO DE BACHILLER", [
            A("1", "Requisitos del bachiller",
              "Para obtener el grado de bachiller se requiere haber egresado, aprobar un trabajo de "
              "investigación y acreditar el conocimiento de un idioma extranjero, de preferencia inglés.",
              ["¿Cuáles son los requisitos para obtener el grado de bachiller?"],
              ["que necesito para sacar el bachiller?"], "trabajo de investigación"),
            A("2", "Idioma extranjero",
              "El idioma se acredita con nivel B1 mediante el centro de idiomas de la universidad o un "
              "certificado internacional con no más de dos años de antigüedad.",
              ["¿Qué nivel de idioma extranjero se exige para el bachiller?"],
              ["mi certificado de ingles de hace tres años me sirve?"], "dos años"),
            A("3", "Trabajo de investigación",
              "El trabajo de investigación se desarrolla en las asignaturas de investigación del último año y "
              "puede ser individual o en pareja.",
              ["¿El trabajo de investigación del bachiller puede hacerse en pareja?"],
              ["el trabajo de investigacion lo puedo hacer con un compañero?"], "en pareja"),
        ]),
        ("CAPÍTULO II: DEL TÍTULO PROFESIONAL", [
            A("4", "Modalidades de titulación",
              "El título profesional se obtiene por sustentación de tesis o por trabajo de suficiencia "
              "profesional. Esta segunda modalidad exige tres años de experiencia en la especialidad.",
              ["¿Qué modalidades existen para obtener el título profesional?"],
              ["puedo titularme sin hacer tesis?"], "suficiencia profesional"),
            A("5", "Originalidad",
              "Toda tesis o trabajo se revisa con software de similitud. El porcentaje de similitud no puede "
              f"superar {p['similitud']}%, excluidas citas y bibliografía.",
              ["¿Cuál es el porcentaje máximo de similitud permitido en una tesis?"],
              ["cuanto de turnitin me aceptan en la tesis?"], f"{p['similitud']}%"),
            A("6", "Sustentación",
              "El jurado está integrado por tres docentes. Si la sustentación es desaprobada, el graduando "
              "puede sustentar nuevamente en un plazo no menor de tres meses.",
              ["¿Cuándo se puede volver a sustentar una tesis desaprobada?"],
              ["si me jalan en la sustentacion cuando puedo volver a sustentar?"], "tres meses"),
        ]),
        ("CAPÍTULO III: DEL TRÁMITE", [
            A("7", "Derechos",
              f"El derecho de grado de bachiller es S/ {p['costo_bachiller']} y el de título profesional, "
              f"S/ {p['costo_titulo']}.",
              ["¿Cuánto cuesta el trámite del grado de bachiller?"],
              ["cuanto cuesta tramitar el bachiller?", "cuanto me sale sacar el titulo?"],
              f"S/ {p['costo_bachiller']}"),
            A("8", "Expedición del diploma",
              f"El diploma se expide en un plazo de {p['dias_diploma']} días hábiles desde la aprobación en "
              "Consejo Universitario y se inscribe en el registro nacional de grados y títulos.",
              ["¿En cuánto tiempo se entrega el diploma?"],
              ["cuanto demora en salir mi diploma?"], f"{p['dias_diploma']} días hábiles"),
        ]),
    ]
    return Documento("RG-2024", "Reglamento de Grados y Títulos", "2024-02-10", "2024-03-01", caps)


def reglamento_becas(p: dict) -> Documento:
    A = Articulo
    caps = [
        ("CAPÍTULO I: DE LAS BECAS", [
            A("1", "Beca de excelencia",
              "El primer puesto de cada carrera en el semestre recibe beca de 100% de la pensión en el "
              "semestre siguiente; el segundo puesto, 50%.",
              ["¿Qué beca recibe el primer puesto de la carrera?"],
              ["si saco primer puesto me becan?"], "100%"),
            A("2", "Beca socioeconómica",
              "Cubre hasta 50% de la pensión. Para mantenerla se requiere promedio ponderado semestral mínimo "
              f"de {p['promedio_beca']} y no desaprobar asignaturas.",
              ["¿Qué promedio se necesita para mantener la beca socioeconómica?"],
              ["que nota tengo que sacar para no perder mi beca?"], str(p["promedio_beca"])),
            A("3", "Pérdida de la beca",
              "La beca se pierde al desaprobar una asignatura, al no alcanzar el promedio exigido o por "
              "sanción disciplinaria.",
              ["¿En qué casos se pierde una beca?"],
              ["si jalo un curso pierdo la beca?"], "desaprobar una asignatura"),
            A("4", "Beca deportiva y cultural",
              "Los estudiantes que representan a la universidad en competencias oficiales pueden recibir "
              "entre 25% y 75% de beca.",
              ["¿Qué porcentaje cubre la beca deportiva?"],
              ["juego en la seleccion de voley de la u, me dan beca?"], "25%"),
        ]),
        ("CAPÍTULO II: DEL BIENESTAR", [
            A("5", "Seguro de accidentes",
              "Todo estudiante matriculado cuenta con un seguro contra accidentes que cubre la atención de "
              "emergencia dentro y fuera del campus.",
              ["¿Los estudiantes cuentan con seguro contra accidentes?"],
              ["tengo seguro si me accidento en la universidad?"], "seguro contra accidentes"),
            A("6", "Tutoría",
              "La tutoría es obligatoria para estudiantes en tercera matrícula o en matrícula condicionada, "
              "con un mínimo de cuatro sesiones por semestre.",
              ["¿Quiénes deben llevar tutoría obligatoria?"],
              ["me obligan a ir a tutoria?"], "cuatro sesiones"),
            A("7", "Atención psicopedagógica",
              f"El servicio psicopedagógico es gratuito y ofrece hasta {p['sesiones_psico']} sesiones por "
              "semestre a cada estudiante.",
              ["¿Cuántas sesiones de atención psicopedagógica ofrece la universidad?"],
              ["la universidad tiene psicologo gratis?"], f"{p['sesiones_psico']} sesiones"),
        ]),
    ]
    return Documento("RB-2025", "Reglamento de Becas y Bienestar Estudiantil", "2025-01-20", "2025-03-01", caps)


def reglamento_disciplina(p: dict) -> Documento:
    A = Articulo
    caps = [
        ("TÍTULO ÚNICO: DEL RÉGIMEN DISCIPLINARIO", [
            A("1", "Faltas", "Las faltas se clasifican en leves, graves y muy graves según el daño causado y la "
              "reincidencia.",
              ["¿Cómo se clasifican las faltas disciplinarias?"],
              ["que tipos de faltas hay en la u?"], "leves, graves y muy graves"),
            A("2", "Sanciones",
              "Las sanciones son amonestación escrita, suspensión de uno a dos semestres y separación "
              "definitiva.",
              ["¿Qué sanciones disciplinarias existen?"],
              ["me pueden suspender por una falta grave?"], "suspensión de uno a dos semestres"),
            A("3", "Procedimiento",
              "La comisión de disciplina notifica los cargos al estudiante, que tiene cinco días hábiles para "
              "presentar sus descargos.",
              ["¿Qué plazo tiene un estudiante para presentar descargos en un proceso disciplinario?"],
              ["me abrieron un proceso disciplinario, cuanto tiempo tengo para defenderme?"],
              "cinco días hábiles"),
        ]),
    ]
    return Documento("RD-2024", "Reglamento de Disciplina", "2024-02-10", "2024-03-01", caps)


SIN_RESPUESTA = [
    "¿A qué hora abre la biblioteca los sábados?",
    "cuanto cuesta el estacionamiento para alumnos?",
    "¿La universidad tiene convenios de intercambio con universidades de España?",
    "¿Quién es el decano de la Facultad de Ingeniería?",
    "como recupero mi contraseña de la intranet?",
    "¿Cuándo es la ceremonia de graduación de este año?",
    "hay cursos de natacion en verano?",
    "¿Cuánto pagan las empresas por las prácticas preprofesionales?",
    "puedo estudiar dos carreras a la vez?",
    "¿La universidad ofrece residencia para estudiantes de provincia?",
    "cuanto cuesta el menu en la cafeteria?",
    "¿La universidad entrega laptops a los ingresantes?",
    "¿Qué buses llegan a la sede principal?",
    "hay wifi en todo el campus?",
    "¿Puedo llevar a mi perro al campus?",
    "cual es el horario de atencion de registros academicos?",
]


def _a_markdown(doc: Documento, rng: random.Random) -> str:
    """Escribe el documento como si viniera de un PDF: líneas cortadas, guiones y pie de página."""
    lineas = ["---", f"codigo: {doc.codigo}", f"titulo: {doc.titulo}", f"tipo: {doc.tipo}",
              f"aprobado: {doc.aprobado}", f"vigente_desde: {doc.vigente_desde}", "---", "",
              f"# {doc.titulo.upper()}", ""]
    pag, desde_pie = 1, 0
    for capitulo, articulos in doc.capitulos:
        lineas += [f"## {capitulo}", ""]
        for a in articulos:
            encabezado = f"Artículo {a.num}.°" + (f" — {a.titulo}" if a.titulo else "")
            cuerpo = textwrap.wrap(a.texto, width=92)
            if len(cuerpo) > 1 and rng.random() < 0.45:
                cuerpo = _cortar_con_guion(cuerpo, rng)
            lineas += [encabezado, *cuerpo, ""]
            desde_pie += 1
            if desde_pie >= rng.randint(4, 6):
                lineas += [PIE.format(pag=pag), ""]
                pag, desde_pie = pag + 1, 0
    if desde_pie:
        lineas += [PIE.format(pag=pag), ""]
    return "\n".join(lineas)


def _cortar_con_guion(lineas: list[str], rng: random.Random) -> list[str]:
    """Pasa la primera sílaba de la primera palabra larga de la línea siguiente a la anterior, con guion."""
    i = rng.randrange(len(lineas) - 1)
    palabras = lineas[i + 1].split(" ")
    if not palabras or len(palabras[0]) < 8 or not palabras[0].isalpha():
        return lineas
    corte = len(palabras[0]) // 2
    lineas = list(lineas)
    lineas[i] = f"{lineas[i]} {palabras[0][:corte]}-"
    lineas[i + 1] = " ".join([palabras[0][corte:], *palabras[1:]])
    return lineas


def _id(codigo: str, num: str, desde: str | None = None) -> str:
    return f"{codigo}/art-{num}" + (f"@{desde}" if desde else "")


def generar(destino: Path = RAIZ, seed: int = 7) -> dict[str, Path]:
    """Escribe el corpus y las preguntas. Devuelve las rutas."""
    rng = random.Random(seed)
    p = parametros(rng)
    re24 = reglamento_estudios(p)
    rcu, nuevos = resolucion_2026(p)
    docs = [re24, rcu, reglamento_pagos(p), reglamento_grados(p), reglamento_becas(p),
            reglamento_disciplina(p)]

    carpeta = Path(destino) / "corpus"
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob("*.md"):
        viejo.unlink()
    for doc in docs:
        (carpeta / f"{doc.codigo}.md").write_text(_a_markdown(doc, rng), encoding="utf-8")

    modificados = {a.num for a in nuevos}
    preguntas = []

    def agregar(texto, registro, tipo, gold, dato, derogado=None):
        preguntas.append({"id": f"q{len(preguntas) + 1:03d}", "pregunta": texto, "registro": registro,
                          "tipo": tipo, "gold": gold, "dato": dato, "derogado": derogado})

    for doc in docs:
        for _, articulos in doc.capitulos:
            for a in articulos:
                if not a.formal and not a.coloquial:
                    continue
                if doc.tipo == "resolucion":
                    continue
                vigencia = doc.codigo == "RE-2024" and a.num in modificados
                gold = [_id(doc.codigo, a.num, rcu.vigente_desde)] if vigencia else [_id(doc.codigo, a.num)]
                derogado = _id(doc.codigo, a.num) if vigencia else None
                tipo = "vigencia" if vigencia else "normal"
                for f in a.formal:
                    agregar(f, "formal", tipo, gold, a.dato, derogado)
                agregar(rng.choice(a.coloquial), "coloquial", tipo, gold, a.dato, derogado)
    for a in nuevos:
        if a.formal:
            g = [_id("RE-2024", a.num, rcu.vigente_desde)]
            for f in a.formal:
                agregar(f, "formal", "nuevo", g, a.dato)
            agregar(rng.choice(a.coloquial), "coloquial", "nuevo", g, a.dato)
    for texto in SIN_RESPUESTA:
        registro = "formal" if texto.startswith("¿") else "coloquial"
        agregar(texto, registro, "sin_respuesta", [], "")

    # mitad para calibrar (desarrollo) y mitad para reportar (prueba), estratificado por tipo
    for tipo in sorted({q["tipo"] for q in preguntas}):
        grupo = [q for q in preguntas if q["tipo"] == tipo]
        rng.shuffle(grupo)
        for i, q in enumerate(grupo):
            q["split"] = "desarrollo" if i % 2 == 0 else "prueba"

    ruta_preguntas = Path(destino) / "preguntas.json"
    ruta_preguntas.write_text(json.dumps(preguntas, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"corpus": carpeta, "preguntas": ruta_preguntas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--destino", type=Path, default=RAIZ)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rutas = generar(args.destino, args.seed)
    n_docs = len(list(rutas["corpus"].glob("*.md")))
    n_preg = len(json.loads(rutas["preguntas"].read_text(encoding="utf-8")))
    print(f"{n_docs} documentos en {rutas['corpus']} · {n_preg} preguntas en {rutas['preguntas']}")


if __name__ == "__main__":
    main()
