"""
Genera las tablas de origen del modelo de matrícula de la "Universidad Mirasol",
una universidad privada ficticia con sedes en Lima Norte, Lima Centro y Arequipa.

Son las tablas limpias que el modelo semántico importa (en la universidad
salen del pipeline de matrícula), una por archivo Parquet:

    periodo, sede, carrera, curso, alumno      dimensiones
    matricula                                  una fila por alumno y periodo
    seccion                                    secciones abiertas con vacantes
    inscripcion                                una fila por alumno y sección

Patrones que trae:
  - el primer semestre del año ingresa casi el doble que el segundo
  - en 2026-2 ingresan menos alumnos que en 2025-2 aunque la matrícula total crece
  - quien no paga la primera cuota se retira de todos sus cursos más seguido
  - una parte de los matriculados lleva menos de 12 créditos (no es alumno regular)
  - las secciones de primer ciclo se programan con la demanda del año anterior,
    así que cuando bajan los ingresantes quedan secciones con poca ocupación
  - algunos alumnos que dejaron de estudiar vuelven (reincorporados)

Uso:
    python datos/generar_datos.py                  # ~5 s
    python datos/generar_datos.py --escala 0.1     # versión chica para pruebas
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

SALIDA_DEFECTO = Path(__file__).parent / "parquet"

PERIODOS = ["2024-1", "2024-2", "2025-1", "2025-2", "2026-1", "2026-2"]
# ingresantes por periodo relativos a 2024-1
INGRESO_RELATIVO = {"2024-1": 1.00, "2024-2": 0.55, "2025-1": 1.06, "2025-2": 0.60,
                    "2026-1": 1.10, "2026-2": 0.55}
INGRESANTES_BASE = 2000

SEDES = [(1, "Lima Norte", "Lima", 0.45), (2, "Lima Centro", "Lima", 0.35),
         (3, "Arequipa", "Arequipa", 0.20)]
CARRERAS = [
    (1, "Ingeniería Industrial", "Ingeniería", 0.17),
    (2, "Ingeniería de Sistemas", "Ingeniería", 0.14),
    (3, "Ingeniería Civil", "Ingeniería", 0.10),
    (4, "Administración", "Negocios", 0.15),
    (5, "Contabilidad", "Negocios", 0.10),
    (6, "Marketing", "Negocios", 0.08),
    (7, "Psicología", "Ciencias Humanas y Derecho", 0.14),
    (8, "Derecho", "Ciencias Humanas y Derecho", 0.12),
]
CICLOS = 10
CURSOS_POR_CICLO = 5
VACANTES = {1: 30, 2: 30, 3: 25}


def _catalogos() -> dict[str, pd.DataFrame]:
    periodo = pd.DataFrame({
        "id_periodo": range(1, len(PERIODOS) + 1),
        "periodo": PERIODOS,
        "anio": [int(p[:4]) for p in PERIODOS],
        "semestre": [int(p[-1]) for p in PERIODOS],
        "orden": range(1, len(PERIODOS) + 1),
    })
    sede = pd.DataFrame(SEDES, columns=["id_sede", "sede", "ciudad", "peso"]).drop(columns="peso")
    carrera = pd.DataFrame(CARRERAS, columns=["id_carrera", "carrera", "facultad", "peso"]).drop(columns="peso")
    filas = []
    for id_carrera, nombre, _, _ in CARRERAS:
        for ciclo in range(1, CICLOS + 1):
            for k in range(1, CURSOS_POR_CICLO + 1):
                filas.append({
                    "id_curso": id_carrera * 1000 + ciclo * 10 + k,
                    "curso": f"{nombre.split()[-1][:3].upper()}-{ciclo:02d}{k}",
                    "id_carrera": id_carrera,
                    "ciclo": ciclo,
                    "creditos": 4 if k <= 2 else 3,
                })
    curso = pd.DataFrame(filas)
    return {"periodo": periodo, "sede": sede, "carrera": carrera, "curso": curso}


def generar(salida: Path = SALIDA_DEFECTO, escala: float = 1.0, seed: int = 11) -> Path:
    """Escribe los Parquet en `salida` y devuelve la carpeta."""
    rng = np.random.default_rng(seed)
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    cat = _catalogos()
    cursos = cat["curso"]
    creditos_curso = dict(zip(cursos["id_curso"], cursos["creditos"]))

    peso_sede = np.array([s[3] for s in SEDES])
    peso_carrera = np.array([c[3] for c in CARRERAS])

    # población inicial: alumnos que ya estudiaban antes de 2024-1
    alumnos: list[dict] = []
    activos: dict[int, dict] = {}   # id -> estado del alumno
    fuera: dict[int, dict] = {}     # dejaron de estudiar, pueden volver

    def nuevo_alumno(ciclo: int, periodo_ingreso: str) -> dict:
        a = {
            "id_alumno": len(alumnos) + 1,
            "id_sede": int(rng.choice([1, 2, 3], p=peso_sede)),
            "id_carrera": int(rng.choice(range(1, 9), p=peso_carrera)),
            "ciclo": ciclo,
            "periodo_ingreso": periodo_ingreso,
            "tipo_colegio": "Público" if rng.random() < 0.58 else "Privado",
            "modalidad": "Semipresencial" if rng.random() < 0.18 else "Presencial",
        }
        alumnos.append(a)
        return a

    for ciclo in range(2, CICLOS + 1):
        # en 2024-1 los ciclos impares vienen de un ingreso de primer semestre (más grande)
        paridad = 1.0 if ciclo % 2 == 1 else 0.55
        n = int(INGRESANTES_BASE * escala * 0.68 * paridad * (0.93 ** (ciclo - 2)))
        for _ in range(n):
            a = nuevo_alumno(ciclo, "anterior")
            activos[a["id_alumno"]] = a

    matriculas, inscripciones, secciones = [], [], []
    demanda_previa: dict[tuple[int, int, int], int] = {}  # (semestre, sede, curso) -> inscritos
    id_seccion = 0

    for id_periodo, periodo in enumerate(PERIODOS, start=1):
        semestre = int(periodo[-1])
        # 1. quién se matricula
        del_periodo = []
        for a in activos.values():
            tipo = a.pop("tipo_proximo", "Continuador")
            del_periodo.append((a, tipo))
        n_ing = int(INGRESANTES_BASE * escala * INGRESO_RELATIVO[periodo] * rng.normal(1, 0.02))
        # la semipresencial gana peso con los años
        p_semi = 0.18 + 0.04 * (id_periodo - 1)
        for _ in range(n_ing):
            a = nuevo_alumno(1, periodo)
            a["modalidad"] = "Semipresencial" if rng.random() < p_semi else "Presencial"
            activos[a["id_alumno"]] = a
            del_periodo.append((a, "Ingresante"))

        # 2. matrícula, pago y carga
        demanda: dict[tuple[int, int], list[int]] = {}
        estado_mat = []
        for a, tipo in del_periodo:
            p_pago = 0.93 if tipo == "Ingresante" else 0.87 - (0.05 if periodo == "2026-2" else 0)
            pago = bool(rng.random() < p_pago)
            p_retiro = 0.03 if pago else 0.22
            retiro_total = bool(rng.random() < p_retiro)
            # carga: la mayoría lleva los cinco cursos de su ciclo; algunos menos
            r = rng.random()
            n_cursos = 5 if r < 0.72 else (4 if r < 0.86 else (3 if r < 0.95 else 2))
            if a["modalidad"] == "Semipresencial" and rng.random() < 0.35:
                n_cursos = min(n_cursos, 3)
            base = a["id_carrera"] * 1000 + a["ciclo"] * 10
            elegidos = sorted(rng.choice(range(1, 6), size=n_cursos, replace=False))
            cursos_al = [base + k for k in elegidos]
            for c in cursos_al:
                demanda.setdefault((a["id_sede"], c), []).append(a["id_alumno"])
            estado_mat.append((a, tipo, pago, retiro_total, cursos_al))

        # 3. secciones: se programan con lo inscrito un año antes en el mismo semestre
        seccion_de: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for (sede, c), ids in demanda.items():
            cap = VACANTES[sede]
            previo = demanda_previa.get((semestre, sede, c))
            plan = previo * rng.normal(1.03, 0.04) if previo else len(ids) * 1.05
            # el tamaño de sección se ajusta a lo planificado, entre 20 y el aforo del aula
            n_sec = max(1, math.ceil(plan / cap))
            vac = int(min(cap, max(20, 5 * math.ceil(plan / n_sec / 5))))
            lista = [vac] * n_sec
            if sum(lista) < len(ids):              # si no alcanza, primero se amplían
                lista = [cap] * n_sec
            while sum(lista) < len(ids):           # y si igual no alcanza, se abre otra
                lista.append(cap)
            ids_sec = []
            for v in lista:
                id_seccion += 1
                ids_sec.append((id_seccion, v))
                secciones.append({"id_seccion": id_seccion, "id_periodo": id_periodo,
                                  "id_sede": sede, "id_curso": c, "vacantes": v})
            seccion_de[(sede, c)] = ids_sec
            demanda_previa[(semestre, sede, c)] = len(ids)

        # reparto: las secciones se llenan en orden, como en la matrícula por turnos
        asignada: dict[tuple[int, int], dict[int, int]] = {}
        for (sede, c), ids in demanda.items():
            cupos = [s for s, v in seccion_de[(sede, c)] for _ in range(v)]
            orden = rng.permutation(ids)
            asignada[(sede, c)] = {int(id_al): cupos[i] for i, id_al in enumerate(orden)}

        for a, tipo, pago, retiro_total, cursos_al in estado_mat:
            creditos_vig = 0
            for c in cursos_al:
                retirado = retiro_total or rng.random() < 0.05
                if not retirado:
                    creditos_vig += creditos_curso[c]
                inscripciones.append({
                    "id_alumno": a["id_alumno"],
                    "id_seccion": asignada[(a["id_sede"], c)][a["id_alumno"]],
                    "creditos": creditos_curso[c],
                    "estado": "Retirado" if retirado else "Vigente",
                })
            if creditos_vig == 0:  # se retiró de cada curso por separado: también es retiro total
                retiro_total = True
            matriculas.append({
                "id_alumno": a["id_alumno"], "id_periodo": id_periodo,
                "id_sede": a["id_sede"], "id_carrera": a["id_carrera"],
                "modalidad": a["modalidad"], "tipo_alumno": tipo, "ciclo": a["ciclo"],
                "creditos_vigentes": creditos_vig, "pago_primera_cuota": pago,
                "retiro_total": retiro_total,
            })

        # 4. quién vuelve el siguiente periodo
        for a, tipo, pago, retiro_total, _ in estado_mat:
            p_sigue = 0.90 if a["ciclo"] > 1 else 0.80
            if not pago:
                p_sigue -= 0.25
            if retiro_total:
                p_sigue -= 0.40
            if not retiro_total:
                a["ciclo"] += 1
            if a["ciclo"] > CICLOS:
                activos.pop(a["id_alumno"])          # egresa
            elif rng.random() > p_sigue:
                fuera[a["id_alumno"]] = activos.pop(a["id_alumno"])
        for id_al in list(fuera):
            if rng.random() < 0.05:
                a = fuera.pop(id_al)
                a["tipo_proximo"] = "Reincorporado"
                activos[id_al] = a

    tablas = dict(cat)
    tablas["alumno"] = pd.DataFrame(alumnos)[["id_alumno", "periodo_ingreso", "tipo_colegio"]]
    tablas["alumno"].insert(1, "codigo", [f"U{i:07d}" for i in tablas["alumno"]["id_alumno"]])
    tablas["matricula"] = pd.DataFrame(matriculas)
    tablas["seccion"] = pd.DataFrame(secciones)
    insc = pd.DataFrame(inscripciones)
    insc.insert(0, "id_inscripcion", range(1, len(insc) + 1))
    tablas["inscripcion"] = insc

    for nombre, df in tablas.items():
        df.to_parquet(salida / f"{nombre}.parquet", index=False)
    return salida


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--salida", type=Path, default=SALIDA_DEFECTO)
    p.add_argument("--escala", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()
    ruta = generar(a.salida, a.escala, a.seed)
    for f in sorted(ruta.glob("*.parquet")):
        print(f"{f.name:<22} {len(pd.read_parquet(f)):>9,} filas")


if __name__ == "__main__":
    main()
