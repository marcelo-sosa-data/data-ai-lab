"""
Genera los datos de la Universidad Qhapaq Ñan (ficticia): tres sedes, ocho
carreras, modalidad presencial y semipresencial, periodos 2023-1 a 2026-2.

Cada alumno tiene un "compromiso" latente que se mueve semana a semana. De él
salen la asistencia, la actividad en el aula virtual, si rinde las evaluaciones
y, al final, si abandona. Lo que se exporta son solo las huellas que dejaría un
sistema académico real: asistencia por semana, ingresos al aula virtual, notas,
cuotas y retiros. El compromiso nunca se exporta.

Patrones que trae la base:
  - los dos primeros ciclos concentran la deserción; desde el quinto casi nadie se va
  - trabajar, estudiar en semipresencial y vivir a más de 90 minutos suben el riesgo;
    la beca lo baja mucho
  - choques económicos a mitad de semestre: se dejan de pagar las cuotas y la
    asistencia cae unas semanas después
  - choques personales (salud, familia): caída brusca de la asistencia
  - desaprobar el parcial hunde el compromiso; el pico de abandono es la semana 9
  - con dos o más cuotas vencidas la intranet bloquea las evaluaciones
  - con más de 30% de faltas el alumno queda inhabilitado para el final y suele dejar de ir
  - en semipresencial la asistencia en vivo dice poco; el aula virtual dice más
  - el becado que no llega a 13 de promedio pierde la beca y muchos no vuelven
  - la mayoría se va entre semestres: termina el ciclo y no se vuelve a matricular
  - traslados a otra universidad sin ninguna señal previa (buenos alumnos que no vuelven)
  - el alumno que abandona sigue matriculado y figura con asistencia 0, salvo que
    haga el retiro de ciclo (permitido hasta la semana 12)
  - 2026: la pensión sube y la semipresencial ya es un tercio de los ingresantes

El periodo 2026-2 está en curso: los datos llegan hasta la semana 10.

Uso:
    python datos/generar_datos.py                 # base completa (~10 s)
    python datos/generar_datos.py --escala 0.15   # menos alumnos, para pruebas
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

RUTA_DEFECTO = Path(__file__).parent / "universidad.duckdb"
PRIMER_PERIODO_SIMULADO = (2018, 1)   # años de calentamiento para tener todos los ciclos
PRIMER_PERIODO_EXPORTADO = (2023, 1)
ULTIMO_PERIODO = (2026, 2)
SEMANA_CORTE_ULTIMO = 10
SEMANAS = 16
SEMANA_LIMITE_RETIRO = 12
CICLOS = 10
SEMANAS_CUOTA = (2, 6, 10, 14)
EVALUACIONES = (("PC1", 4, 0.15), ("Parcial", 8, 0.30), ("PC2", 12, 0.15), ("Final", 16, 0.40))

SEDES = {"LN": "Lima Norte", "LC": "Lima Centro", "AQ": "Arequipa"}
PESO_SEDE = (0.45, 0.35, 0.20)

# código, nombre, peso en ingresantes, dificultad (baja la nota), ajuste al compromiso
CARRERAS = [
    ("IND", "Ingeniería Industrial", 0.17, 0.6, 0.00),
    ("SIS", "Ingeniería de Sistemas", 0.14, 0.7, -0.05),
    ("CIV", "Ingeniería Civil", 0.10, 0.9, -0.05),
    ("ADM", "Administración", 0.15, 0.2, 0.00),
    ("CON", "Contabilidad", 0.10, 0.4, 0.05),
    ("MKT", "Marketing", 0.08, 0.1, -0.05),
    ("PSI", "Psicología", 0.14, 0.2, 0.05),
    ("DER", "Derecho", 0.12, 0.3, 0.05),
]
ESCALAS = "ABCDE"   # escala de pensión: A es la más baja


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def periodos_entre(inicio: tuple[int, int], fin: tuple[int, int]) -> list[tuple[int, int]]:
    out, (a, s) = [], inicio
    while (a, s) <= fin:
        out.append((a, s))
        a, s = (a, 2) if s == 1 else (a + 1, 1)
    return out


def nombre_periodo(p: tuple[int, int]) -> str:
    return f"{p[0]}-{p[1]}"


def _nuevos_ingresantes(rng, n, periodo, id_inicial):
    anio = periodo[0] + (periodo[1] - 1) / 2
    p_semi = np.clip(0.15 + 0.022 * (anio - 2018), 0.15, 0.34)
    semi = rng.random(n) < p_semi
    sede = rng.choice(3, n, p=PESO_SEDE)
    carrera = rng.choice(len(CARRERAS), n, p=[c[2] for c in CARRERAS])
    edad = np.where(semi, rng.gamma(4, 2.2, n) + 20, rng.choice([16, 17, 18, 19, 20], n, p=[.08, .42, .32, .12, .06]))
    trabaja = rng.random(n) < np.where(semi, 0.86, 0.20)
    publico = rng.random(n) < 0.56
    p_esc = np.where(publico[:, None], [[.34, .30, .20, .11, .05]], [[.10, .20, .30, .25, .15]])
    escala = (rng.random(n)[:, None] > np.cumsum(p_esc, axis=1)).sum(axis=1)
    primera_gen = rng.random(n) < np.where(publico, 0.52, 0.28)
    habilidad = rng.normal(0, 1, n) + 0.15 * (~publico)
    puntaje = np.clip(np.round(55 + 12 * habilidad + rng.normal(0, 7, n)), 20, 100)
    # tiempo de traslado: Lima Norte y Lima Centro reciben alumnos de lejos
    traslado = np.where(sede == 2, rng.gamma(3, 12, n), rng.gamma(3.2, 19, n))
    traslado = np.clip(np.round(traslado / 5) * 5, 10, 180)
    beca = np.where(rng.random(n) < 0.03 + 0.06 * (habilidad > 1.0), rng.choice([50, 100], n, p=[.7, .3]), 0)
    return dict(
        id_alumno=np.arange(id_inicial, id_inicial + n),
        sede=sede, carrera=carrera, semipresencial=semi, edad_ingreso=np.round(edad).astype(int),
        trabaja=trabaja, colegio_publico=publico, escala=escala, primera_gen=primera_gen,
        habilidad=habilidad, puntaje=puntaje, traslado_min=traslado, beca=beca,
        compromiso_base=rng.normal(0, 0.55, n),
        periodo_ingreso=np.array([nombre_periodo(periodo)] * n),
        # estado entre semestres
        activo=np.ones(n, bool), ciclo=np.ones(n, int), prom_anterior=np.full(n, np.nan),
        desaprobados_acum=np.zeros(n, int), retiros_previos=np.zeros(n, int),
    )


class Estado:
    """Arrays mutables de toda la población (se extienden con cada cohorte)."""

    def __init__(self):
        self.d: dict[str, np.ndarray] = {}

    def extender(self, nuevos: dict):
        for k, v in nuevos.items():
            self.d[k] = np.concatenate([self.d[k], v]) if k in self.d else v

    def __getitem__(self, k):
        return self.d[k]


def _simular_periodo(rng, est: Estado, periodo, semanas: int, exportar: bool):
    d = est.d
    idx = np.flatnonzero(d["activo"])
    n = len(idx)
    anio = periodo[0]
    ciclo = d["ciclo"][idx]
    semi = d["semipresencial"][idx]
    trab = d["trabaja"][idx]
    hab = d["habilidad"][idx]
    beca = d["beca"][idx] > 0
    lejos = (d["traslado_min"][idx] > 90) & ~semi
    car = d["carrera"][idx]
    dific = np.array([c[3] for c in CARRERAS])[car]
    ajuste_car = np.array([c[4] for c in CARRERAS])[car]
    prom_ant = d["prom_anterior"][idx]
    desap = d["desaprobados_acum"][idx]

    choque_anio = 0.25 if anio >= 2026 else 0.0   # alza de pensión 2026
    tension = (2 - d["escala"][idx]) * 0.22 + 0.30 * d["primera_gen"][idx] + 0.25 * trab \
        - 0.7 * beca + choque_anio + rng.normal(0, 0.45, n)

    c0 = (1.05 + 0.32 * hab + d["compromiso_base"][idx] - 0.30 * tension - 0.22 * trab - 0.25 * semi
          - 0.25 * lejos - 0.35 * (ciclo == 1) + 0.08 * np.minimum(ciclo - 1, 6) + 0.45 * beca + ajuste_car
          - 0.05 * np.minimum(desap, 6) - 0.25 * d["retiros_previos"][idx]
          + np.where(np.isnan(prom_ant), 0, 0.12 * (np.nan_to_num(prom_ant, nan=13) - 13))
          + rng.normal(0, 0.30, n))

    n_cursos = np.where(semi, rng.choice([4, 5], n), rng.choice([5, 6, 6, 7], n))
    n_cursos = np.where(ciclo >= 9, n_cursos - 1, n_cursos)
    creditos = n_cursos * 4 - rng.integers(0, 3, n)

    # choques del semestre
    p_eco = _sig(-3.4 + 0.95 * tension + 0.25 * trab)
    eco = rng.random(n) < p_eco
    sem_eco = rng.integers(1, 14, n)
    pers = rng.random(n) < 0.035
    sem_pers = rng.integers(2, 15, n)
    traslado_ext = rng.random(n) < (0.004 + 0.009 * (ciclo <= 4)) * (1 + 0.6 * (hab > 0.5))

    c = c0.copy()
    abandono = np.zeros(n, int)            # semana en que deja de ir (0 = no abandona en el semestre)
    retiro = np.zeros(n, int)              # semana del retiro formal
    notas = {}
    vencidas = np.zeros(n, int)
    pago_sem = np.full((n, len(SEMANAS_CUOTA)), np.nan)
    # cómo paga cada cuota: a tiempo, tarde o no paga; con choque económico cambia desde esa semana
    p_tiempo = _sig(2.0 - 0.9 * tension + 1.5 * beca)
    asis_rows, lms_rows = [], []
    sesiones_base = np.where(semi, n_cursos, n_cursos * 2)
    ses_acum, asi_acum = np.zeros(n), np.zeros(n)

    for w in range(1, semanas + 1):
        activo_w = (abandono == 0)
        # dinámica del compromiso
        c = c + rng.normal(0, 0.10, n) + 0.05 * (c0 - c)
        c = c - np.where(eco & (w >= sem_eco) & (w <= sem_eco + 2), 0.30, 0)
        c = c - np.where(pers & (w == sem_pers), 1.30, 0) + np.where(pers & (w > sem_pers), 0.06, 0)
        c = c - 0.08 * (vencidas >= 2)
        c = c - np.where(traslado_ext & (w >= semanas - 2), 0.15, 0)

        # cuotas que vencen esta semana
        if w in SEMANAS_CUOTA:
            k = SEMANAS_CUOTA.index(w)
            en_choque = eco & (w >= sem_eco)
            pt = np.where(en_choque, 0.12, p_tiempo)
            u = rng.random(n)
            a_tiempo = u < pt
            no_paga = (u > pt + (1 - pt) * np.where(en_choque, 0.35, 0.75)) | ~activo_w & (rng.random(n) < 0.7)
            atraso = rng.integers(1, 6, n)
            pago_sem[:, k] = np.where(a_tiempo, w - rng.integers(0, 2, n), np.where(no_paga, np.nan, w + atraso))
        # cuotas vencidas e impagas al cierre de la semana w
        vencidas = np.zeros(n, int)
        for k, sv in enumerate(SEMANAS_CUOTA):
            if sv <= w:
                vencidas += np.isnan(pago_sem[:, k]) | (pago_sem[:, k] > w)

        # evaluaciones
        for nombre, sem_ev, _ in EVALUACIONES:
            if w == sem_ev:
                # con dos o más cuotas vencidas la intranet bloquea la evaluación a la mayoría
                bloqueo = (vencidas >= 2) & (rng.random(n) < 0.6)
                rinde = activo_w & ~bloqueo & (rng.random(n) < _sig(2.6 + 1.6 * c))
                nota = np.clip(12.5 + 2.2 * hab + 0.9 * (c - 1.2) - dific + rng.normal(0, 1.7, n), 0, 20)
                notas[nombre] = np.where(rinde, np.round(nota, 1), np.nan)
                if nombre in ("PC1", "Parcial"):
                    golpe = 0.30 if nombre == "PC1" else 0.55
                    c = c - np.where(rinde & (nota < 10.5), golpe, 0) + np.where(rinde & (nota >= 15), 0.08, 0)
                    c = c - np.where(activo_w & ~rinde, 0.25, 0)
                    # el becado que sale mal teme perder la beca (exige 13 de promedio)
                    c = c - np.where(beca & rinde & (nota < 12), 0.35, 0)

        # abandono
        bump = {1: 0.5, 2: 0.4, 9: 1.1, 10: 0.6}.get(w, 0.0) - (0.4 if w >= 13 else 0.0)
        # con más de 30% de faltas queda inhabilitado para el final: muchos dejan de ir ahí mismo
        inhab = (w >= 6) & (asi_acum < 0.70 * np.maximum(ses_acum, 1))
        h = _sig(-5.7 - 1.65 * c + bump + 0.45 * (vencidas >= 2) + 1.2 * inhab)
        nuevos = activo_w & (rng.random(n) < h) & ~traslado_ext
        abandono[nuevos] = w
        hace_retiro = nuevos & (rng.random(n) < 0.30) & (w <= SEMANA_LIMITE_RETIRO)
        retiro[hace_retiro] = np.minimum(w + rng.integers(0, 2, hace_retiro.sum()), SEMANA_LIMITE_RETIRO)

        fuera = (abandono > 0) & (abandono <= w)
        ses = sesiones_base - np.where(w in (8, 16), n_cursos // 2, 0)
        # en semipresencial hay pocas sesiones en vivo: la señal está más en el aula virtual
        p_as = _sig(1.7 + np.where(semi, 0.6, 1.25) * c - 0.40 * lejos - 0.20 * trab - (0.45 if w == 1 else 0)
                    - (0.2 if w == 16 else 0))
        asist = np.where(fuera, 0, rng.binomial(ses, np.clip(p_as, 0, 1)))
        ses_acum += ses
        asi_acum += asist
        if exportar:
            sigue_matriculado = (retiro == 0) | (retiro > w)
            asis_rows.append(np.column_stack([idx[sigue_matriculado], np.full(sigue_matriculado.sum(), w),
                                              ses[sigue_matriculado], asist[sigue_matriculado]]))
            lam = np.exp(1.15 + np.where(semi, 0.85, 0.40) * c + 0.55 * semi - (0.3 if w == 1 else 0))
            ingresos = np.where(fuera, rng.binomial(1, 0.08, n), rng.poisson(np.clip(lam, 0.05, 40)))
            minutos = np.round(ingresos * rng.gamma(3, 6, n)).astype(int)
            tareas = np.where(w == 1, 0, rng.binomial(n_cursos, 0.45))
            entregadas = np.where(fuera, 0, rng.binomial(tareas, np.clip(_sig(0.9 + 1.1 * c + 0.3 * hab), 0, 1)))
            lms_rows.append(np.column_stack([idx[sigue_matriculado], np.full(sigue_matriculado.sum(), w),
                                             ingresos[sigue_matriculado], minutos[sigue_matriculado],
                                             tareas[sigue_matriculado], entregadas[sigue_matriculado]]))

    # cierre del semestre
    completo = semanas == SEMANAS
    prom = sum(np.nan_to_num(notas[nm], nan=0.0) * peso for nm, _, peso in EVALUACIONES) if completo else None
    resultado = dict(idx=idx, ciclo=ciclo, creditos=creditos, n_cursos=n_cursos, beca=d["beca"][idx],
                     prom_ant=prom_ant, desap=desap, retiros_prev=d["retiros_previos"][idx],
                     abandono=abandono, retiro=retiro, notas=notas, pago_sem=pago_sem,
                     eco=eco, pers=pers, traslado=traslado_ext, asis=asis_rows, lms=lms_rows)
    if not completo:
        return resultado

    termino = abandono == 0
    desap_sem = np.where(termino, rng.binomial(n_cursos, np.clip(_sig((10.5 - prom) * 1.1 - 0.6), 0, 1)), n_cursos)
    inhabilitado = asi_acum < 0.70 * ses_acum
    desap_sem = np.where(termino & inhabilitado, np.maximum(desap_sem, n_cursos - 1), desap_sem)
    deuda = np.isnan(pago_sem).sum(axis=1)
    egresa = termino & (ciclo >= CICLOS) & ((desap_sem <= 1) | (rng.random(n) < 0.6))
    pierde_beca = beca & (prom < 13)
    p_vuelve = _sig(3.4 + 1.05 * c - 0.30 * desap_sem - 1.1 * (deuda >= 2) + 0.7 * beca - 1.6 * pierde_beca
                    - 0.25 * semi)
    vuelve = termino & ~egresa & ~traslado_ext & (rng.random(n) < p_vuelve)
    # unos pocos que abandonaron en el semestre vuelven al siguiente
    vuelve |= (abandono > 0) & (rng.random(n) < 0.05)

    d["activo"][idx] = vuelve
    d["ciclo"][idx] = np.where(termino, np.minimum(ciclo + 1, CICLOS), ciclo)
    d["prom_anterior"][idx] = np.where(termino, np.round(prom, 2), d["prom_anterior"][idx])
    d["desaprobados_acum"][idx] = desap + desap_sem * termino
    d["retiros_previos"][idx] += (abandono > 0)
    resultado.update(egresa=egresa, vuelve=vuelve, prom=prom)
    return resultado


def generar(ruta: Path = RUTA_DEFECTO, escala: float = 1.0, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    est = Estado()
    periodos = periodos_entre(PRIMER_PERIODO_SIMULADO, ULTIMO_PERIODO)
    tablas = {k: [] for k in ("matriculas", "asistencia", "aula_virtual", "evaluaciones", "cuotas",
                              "retiros", "egresados", "aux_causas")}
    siguiente_id = 1
    for p in periodos:
        anio = p[0]
        base = 1700 if p[1] == 1 else 1100
        n_ing = int(round(base * escala * (1 + 0.02 * (anio - 2018)) * (0.93 if anio == 2026 else 1.0)))
        est.extender(_nuevos_ingresantes(rng, n_ing, p, siguiente_id))
        siguiente_id += n_ing
        exportar = p >= PRIMER_PERIODO_EXPORTADO
        semanas = SEMANA_CORTE_ULTIMO if p == ULTIMO_PERIODO else SEMANAS
        r = _simular_periodo(rng, est, p, semanas, exportar)
        if not exportar:
            continue
        per = nombre_periodo(p)
        ids = est["id_alumno"][r["idx"]]
        tablas["matriculas"].append(pd.DataFrame({
            "id_alumno": ids, "periodo": per, "ciclo": r["ciclo"], "cursos": r["n_cursos"],
            "creditos": r["creditos"], "beca_pct": r["beca"], "promedio_anterior": r["prom_ant"],
            "desaprobados_acumulados": r["desap"], "retiros_previos": r["retiros_prev"]}))
        a = np.vstack(r["asis"])
        tablas["asistencia"].append(pd.DataFrame({
            "id_alumno": est["id_alumno"][a[:, 0]], "periodo": per, "semana": a[:, 1],
            "sesiones": a[:, 2], "asistidas": a[:, 3]}))
        lm = np.vstack(r["lms"])
        tablas["aula_virtual"].append(pd.DataFrame({
            "id_alumno": est["id_alumno"][lm[:, 0]], "periodo": per, "semana": lm[:, 1], "ingresos": lm[:, 2],
            "minutos": lm[:, 3], "tareas": lm[:, 4], "tareas_entregadas": lm[:, 5]}))
        for nombre, sem_ev, _ in EVALUACIONES:
            if nombre in r["notas"]:
                tablas["evaluaciones"].append(pd.DataFrame({
                    "id_alumno": ids, "periodo": per, "evaluacion": nombre, "semana": sem_ev,
                    "nota": r["notas"][nombre]}))
        for k, sv in enumerate(SEMANAS_CUOTA):
            if sv <= semanas:
                pago = r["pago_sem"][:, k]
                pago = np.where(pago > semanas, np.nan, pago)      # lo que se paga después del corte no se ve
                tablas["cuotas"].append(pd.DataFrame({
                    "id_alumno": ids, "periodo": per, "cuota": k + 1, "semana_vencimiento": sv,
                    "semana_pago": pago}))
        m = r["retiro"] > 0
        tablas["retiros"].append(pd.DataFrame({"id_alumno": ids[m], "periodo": per, "semana": r["retiro"][m],
                                               "tipo": "retiro de ciclo"}))
        if "egresa" in r:
            tablas["egresados"].append(pd.DataFrame({"id_alumno": ids[r["egresa"]], "periodo": per}))
            deserta = ~r["vuelve"] & ~r["egresa"]
            causa = np.select([r["traslado"], r["eco"], r["pers"]], ["traslado", "económica", "personal"],
                              "académica o desenganche")
            tablas["aux_causas"].append(pd.DataFrame({
                "id_alumno": ids[deserta], "periodo": per, "causa": causa[deserta],
                "semana_abandono_real": np.where(r["abandono"][deserta] > 0, r["abandono"][deserta], 17)}))

    d = est.d
    vistos = np.unique(pd.concat(tablas["matriculas"]).id_alumno.to_numpy()) - 1
    alumnos = pd.DataFrame({
        "id_alumno": d["id_alumno"][vistos],
        "codigo": [f"U{pi[:4]}{i:05d}" for pi, i in zip(d["periodo_ingreso"][vistos], d["id_alumno"][vistos])],
        "sede": np.array(list(SEDES.values()))[d["sede"][vistos]],
        "carrera": np.array([c[1] for c in CARRERAS])[d["carrera"][vistos]],
        "modalidad": np.where(d["semipresencial"][vistos], "semipresencial", "presencial"),
        "periodo_ingreso": d["periodo_ingreso"][vistos],
        "edad_ingreso": d["edad_ingreso"][vistos],
        "colegio": np.where(d["colegio_publico"][vistos], "público", "privado"),
        "escala_pension": np.array(list(ESCALAS))[d["escala"][vistos]],
        "primera_generacion": d["primera_gen"][vistos],
        "trabaja": d["trabaja"][vistos],
        "tiempo_traslado_min": d["traslado_min"][vistos].astype(int),
        "puntaje_ingreso": d["puntaje"][vistos].astype(int),
    })
    periodos_df = pd.DataFrame({"periodo": [nombre_periodo(p) for p in periodos_entre(PRIMER_PERIODO_EXPORTADO,
                                                                                         ULTIMO_PERIODO)]})
    periodos_df["semanas_con_datos"] = np.where(periodos_df.periodo == nombre_periodo(ULTIMO_PERIODO),
                                                SEMANA_CORTE_ULTIMO, SEMANAS)

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        ruta.unlink()
    con = duckdb.connect(str(ruta))
    con.register("t", alumnos)
    con.execute("CREATE TABLE alumnos AS SELECT * FROM t")
    con.register("t", periodos_df)
    con.execute("CREATE TABLE periodos AS SELECT * FROM t")
    for nombre, partes in tablas.items():
        df = pd.concat(partes, ignore_index=True)
        if nombre == "cuotas":
            df["semana_pago"] = df.semana_pago.astype("Int64")
        con.register("t", df)
        con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM t")
    con.execute("COMMENT ON TABLE aux_causas IS 'Causa simulada de cada deserción. Solo para análisis: "
                "el modelo no la lee.'")
    con.close()
    return ruta


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ruta", type=Path, default=RUTA_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    print(generar(a.ruta, a.escala, a.seed))
