"""
Genera el export del sistema de trámites de la Universidad Mirasol (ficticia):
convalidaciones de cursos y retiros de curso registrados entre enero y
noviembre de 2026, con el log de cada actividad.

El log sale de una simulación de eventos discretos (SimPy) con las áreas,
su personal y sus horarios. Eso es lo que hace interesante el análisis:

  - Dirección de Carrera atiende trámites solo de 14:00 a 17:00, y los
    retiros solo martes y jueves de 13:00 a 17:00; en febrero cada director
    toma dos semanas de vacaciones
  - el decano firma resoluciones en lote los viernes a las 10:00 y una de
    cada ocho semanas no firma
  - en convalidación el pago se verifica al final, después de la firma; quien
    no pagó recibe la observación cuando ya se hizo todo el trabajo
  - lo que observa Dirección vuelve a empezar por Secretaría
  - los retiros se juntan antes de la fecha límite y, si Registros los
    atiende después de esa fecha, necesitan una resolución de excepción
  - Registros pierde a una persona en las semanas de matrícula
  - desvíos de control: convalidaciones registradas sin pago verificado,
    expedientes que saltan la revisión de Secretaría, retiros sin visto bueno

El mismo motor corre con las reglas rediseñadas (`Reglas`) sobre los mismos
casos y el mismo azar por caso, para tener contra qué revisar la simulación
del análisis. Eso solo se puede hacer porque los datos son sintéticos.

Uso:
    python datos/generar_datos.py                 # ~5,600 trámites (~15 s)
    python datos/generar_datos.py --escala 0.1    # base chica para pruebas
"""

from __future__ import annotations

import argparse
import sys
import zlib
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import simpy

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from tramites import catalogos as K  # noqa: E402
from tramites.calendario import a_calendario, a_habiles, dia_habil, momentos_semanales  # noqa: E402

DESTINO = Path(__file__).parent
N_CONVALIDACIONES = 2_300
N_RETIROS = 3_300
FIN_REGISTRO = datetime(2026, 11, 13, 23, 59)
FIN_SIMULACION = datetime(2027, 3, 31)

# peso de cada mes (ene..nov) en las convalidaciones: traslados antes de cada semestre
PESO_MES_CONV = [0.13, 0.19, 0.16, 0.04, 0.02, 0.04, 0.15, 0.17, 0.05, 0.03, 0.02]
VENTANA_RETIRO = [(datetime(2026, 3, 30), K.SEMESTRES[0].limite_retiro),
                  (datetime(2026, 8, 31), K.SEMESTRES[1].limite_retiro)]
SEMANAS_MATRICULA = [(datetime(2026, 3, 2), datetime(2026, 3, 21)),
                     (datetime(2026, 8, 3), datetime(2026, 8, 22))]

USUARIOS = {
    K.SECRETARIA: ["sec.ramos", "sec.quispe", "sec.flores"],
    K.TESORERIA: ["tes.huaman", "tes.vargas"],
    K.REGISTROS: ["reg.castillo", "reg.mendoza"],
    K.DECANATO: ["dec.salazar"],
}
NOMBRES = ["Luis", "María", "José", "Ana", "Carlos", "Rosa", "Jorge", "Lucía", "Miguel", "Carmen",
           "Diego", "Valeria", "Renzo", "Camila", "Kevin", "Fiorella", "Piero", "Alessandra",
           "Bruno", "Milagros", "Jhon", "Katherine", "Fernando", "Gabriela", "Raúl", "Daniela",
           "César", "Andrea", "Óscar", "Sofía", "Hugo", "Mariana", "Iván", "Paola"]
APELLIDOS = ["Quispe", "Flores", "Sánchez", "Rodríguez", "García", "Rojas", "Huamán", "Mamani",
             "Torres", "Chávez", "Ramírez", "Mendoza", "Vargas", "Castillo", "Díaz", "Gutiérrez",
             "Espinoza", "Salazar", "Ccori", "Paredes", "Vásquez", "Cárdenas", "Ríos", "Palomino",
             "Condori", "Ticona", "Herrera", "Medina", "Zevallos", "Aguilar", "Ponce", "Lozano"]


# --------------------------------------------------------------------------
# Casos
# --------------------------------------------------------------------------

def _hora_portal(rng, n):
    """Hora del registro en el portal: de mañana a noche, con pico después de clases."""
    h = rng.choice(np.arange(24), n, p=_PESO_HORA)
    return h + rng.random(n)


_PESO_HORA = np.array([1, .5, .3, .2, .2, .3, .8, 2, 4, 6, 6, 6, 5, 5, 6, 6, 6, 6, 7, 8, 8, 7, 5, 3])
_PESO_HORA = _PESO_HORA / _PESO_HORA.sum()


def generar_casos(escala: float = 1.0, seed: int = 16) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    filas = []

    n = int(N_CONVALIDACIONES * escala)
    meses = rng.choice(np.arange(1, 12), n, p=np.array(PESO_MES_CONV) / sum(PESO_MES_CONV))
    for i, (m, h) in enumerate(zip(meses, _hora_portal(rng, n))):
        dia_max = 30 if m in (4, 6, 9, 11) else (28 if m == 2 else 31)
        dia_min = 5 if m == 1 else 1
        dia = rng.integers(dia_min, (13 if m == 11 else dia_max) + 1)
        filas.append({"tipo": K.CONVALIDACION,
                      "registro": datetime(2026, m, dia) + timedelta(hours=float(h)),
                      "n_cursos": int(np.clip(rng.poisson(3.2) + 1, 1, 9)),
                      "origen": "Traslado externo" if rng.random() < 0.7 else "Cambio de carrera"})

    n = int(N_RETIROS * escala)
    for i in range(n):
        ini, lim = VENTANA_RETIRO[0] if rng.random() < 0.52 else VENTANA_RETIRO[1]
        dur = (lim - ini).total_seconds() / 86400
        # la mayoría pide el retiro en las últimas tres semanas; 3% lo pide tarde
        if rng.random() < 0.03:
            d = dur + rng.uniform(0, 10)
        else:
            d = dur * (1 - rng.beta(1.0, 1.8)) if rng.random() < 0.5 else dur - rng.exponential(9)
            d = float(np.clip(d, 0, dur - 0.05))
        fecha = (ini + timedelta(days=d)).replace(hour=0, minute=0, second=0)
        filas.append({"tipo": K.RETIRO,
                      "registro": fecha + timedelta(hours=float(_hora_portal(rng, 1)[0])),
                      "n_cursos": 1, "origen": None})

    casos = pd.DataFrame(filas).sort_values("registro").reset_index(drop=True)
    casos = casos[casos["registro"] <= FIN_REGISTRO].reset_index(drop=True)
    k = len(casos)
    casos.insert(0, "id_tramite", [f"TR-26-{i:05d}" for i in rng.permutation(np.arange(10_000, 10_000 + k))])
    casos["carrera"] = rng.choice(list(K.CARRERAS), k, p=list(K.CARRERAS.values()))
    casos["sede"] = rng.choice(list(K.SEDES), k, p=list(K.SEDES.values()))
    casos["becado"] = rng.random(k) < 0.14
    ingreso = rng.choice([2021, 2022, 2023, 2024, 2025, 2026], k, p=[.08, .15, .2, .22, .2, .15])
    casos["codigo_alumno"] = [f"U{a % 100:02d}{rng.integers(0, 99_999):05d}" for a in ingreso]
    casos["nombre_alumno"] = [
        f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)} {rng.choice(APELLIDOS)}" for _ in range(k)]
    return casos


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------

class Azar:
    """Un generador por caso y por propósito: los escenarios comparten el mismo azar por caso."""

    def __init__(self, seed: int, idx: int):
        self.seed, self.idx, self._g = seed, idx, {}

    def __call__(self, proposito: str) -> np.random.Generator:
        if proposito not in self._g:
            self._g[proposito] = np.random.default_rng(
                [self.seed, self.idx, zlib.crc32(proposito.encode())])
        return self._g[proposito]

    def u(self, p: str) -> float:
        return float(self(p).random())

    def lognormal(self, p: str, mediana: float, sigma: float) -> float:
        return float(mediana * np.exp(sigma * self(p).standard_normal()))


class Universidad:
    def __init__(self, env: simpy.Environment, reglas: K.Reglas, seed: int):
        self.env, self.reglas, self.seed = env, reglas, seed
        self.sec = simpy.Resource(env, 3)
        self.tes = simpy.Resource(env, 2)
        self.reg = simpy.PriorityResource(env, 2)
        self.dir = {c: simpy.Resource(env, 1) for c in K.CARRERAS}
        self.dir_ret = {c: simpy.Resource(env, 1) for c in K.CARRERAS}
        self.firma = env.event()
        self.firmados: dict[float, int] = {}
        self.eventos: list[tuple] = []
        self.fin_caso: dict[str, tuple] = {}
        rng = np.random.default_rng(seed + 99)
        # vacaciones de cada director: dos semanas seguidas en febrero
        self.vacaciones = {}
        for c in K.CARRERAS:
            ini = datetime(2026, 2, 2) + timedelta(days=int(rng.integers(0, 15)))
            self.vacaciones[c] = {(ini + timedelta(days=d)).date() for d in range(14)}
        self.u_usuario = rng
        env.process(self._decanato())
        for ini, fin in SEMANAS_MATRICULA:
            env.process(self._matricula(ini, fin))

    # -- recursos con horario ---------------------------------------------------

    def _decanato(self):
        rng = np.random.default_rng(self.seed + 7)
        for m in momentos_semanales(list(self.reglas.dias_firma), 10, datetime(2026, 1, 5),
                                    FIN_SIMULACION):
            if m > self.env.now:
                yield self.env.timeout(m - self.env.now)
            if rng.random() < 0.12:   # el decano no está: no hay firma esta vez
                continue
            ev, self.firma = self.firma, self.env.event()
            ev.succeed(m)

    def _matricula(self, ini, fin):
        yield self.env.timeout(a_habiles(ini) - self.env.now)
        with self.reg.request(priority=-1) as r:
            yield r
            yield self.env.timeout(max(0, a_habiles(fin) - self.env.now))

    def _ventana_direccion(self, carrera: str, retiro: bool):
        """Espera hasta que el director atienda: 14-17 h, o martes y jueves 13-17 h para retiros."""
        while True:
            dia, hora = dia_habil(self.env.now)
            desde, dias = (5, (1, 3)) if retiro else (6, (0, 1, 2, 3, 4))
            if dia in self.vacaciones[carrera] or dia.weekday() not in dias or hora > 8.75:
                yield self.env.timeout((self.env.now - hora) + 9 + desde - self.env.now)
            elif hora < desde:
                yield self.env.timeout(desde - hora)
            else:
                return

    # -- registro de eventos ----------------------------------------------------

    def _log(self, caso, actividad, area, fin, inicio=None, usuario=None, en_calendario=False):
        if usuario is None:
            if area == K.DIRECCION:
                usuario = "dir." + caso["carrera"].split()[-1].lower()[:10]
            elif area in USUARIOS:
                usuario = str(self.u_usuario.choice(USUARIOS[area]))
            else:
                usuario = area.lower()
        self.eventos.append((caso["id_tramite"], actividad, area, usuario, inicio, fin, en_calendario))

    def atender(self, caso, az, recurso, actividad, area, horas, carrera=None, retiro=False,
                prioridad=None):
        req = recurso.request(priority=prioridad) if prioridad is not None else recurso.request()
        with req as r:
            yield r
            if carrera:
                yield from self._ventana_direccion(carrera, retiro)
            t0 = self.env.now
            yield self.env.timeout(horas)
            self._log(caso, actividad, area, self.env.now, None if actividad in K.SIN_INICIO else t0)

    def instante(self, caso, actividad, area, minutos=1.0):
        self._log(caso, actividad, area, self.env.now + minutos / 60)

    def estudiante(self, caso, az, actividad, mediana_dias, sigma, p_abandono):
        """El estudiante responde en días calendario; devuelve False si abandona."""
        if az.u(f"abandono_{actividad}") < p_abandono:
            yield self.env.timeout(a_habiles(a_calendario(self.env.now) + timedelta(days=30))
                                   - self.env.now)
            self.instante(caso, K.ARCHIVAR, K.SECRETARIA, 20)
            return False
        dias = az.lognormal(f"demora_{actividad}", mediana_dias, sigma)
        t = a_calendario(self.env.now) + timedelta(days=dias)
        self._log(caso, actividad, K.ESTUDIANTE, t, en_calendario=True)
        yield self.env.timeout(max(0.0, a_habiles(t) - self.env.now))
        return True

    def esperar_firma(self, caso):
        momento = yield self.firma
        n = self.firmados.get(momento, 0)
        self.firmados[momento] = n + 1
        self._log(caso, K.FIRMAR, K.DECANATO, momento + 0.02 * n)
        yield self.env.timeout(momento + 0.02 * n - self.env.now)

    # -- ciclos que se repiten --------------------------------------------------

    def ciclo_secretaria(self, caso, az, actividad, observar, mediana, p_obs, p_obs_rep):
        p, vuelta = p_obs, 0
        while True:
            yield from self.atender(caso, az, self.sec, actividad, K.SECRETARIA,
                                    az.lognormal("dur_sec", mediana, 0.5))
            if az.u(f"obs_sec_{vuelta}") >= p:
                return True
            self.instante(caso, observar, K.SECRETARIA)
            ok = yield from self.estudiante(caso, az, K.SUBSANAR, 2.5, 0.9, 0.07)
            if not ok:
                return False
            p, vuelta = p_obs_rep, vuelta + 1

    def ciclo_tesoreria(self, caso, az, verificar, observar, pagar, p_no, mediana_pago, p_aband):
        yield from self.atender(caso, az, self.tes, verificar, K.TESORERIA,
                                az.lognormal("dur_tes", 0.1, 0.4))
        if az.u("no_pago") >= p_no:
            return True
        self.instante(caso, observar, K.TESORERIA)
        ok = yield from self.estudiante(caso, az, pagar, mediana_pago, 0.8, p_aband)
        if not ok:
            return False
        yield from self.atender(caso, az, self.tes, verificar, K.TESORERIA,
                                az.lognormal("dur_tes2", 0.1, 0.4))
        return True

    def en_paralelo(self, *generadores):
        procesos = [self.env.process(g) for g in generadores]
        yield simpy.AllOf(self.env, procesos)
        return all(p.value for p in procesos)

    def cerrar(self, caso, resultado):
        self.instante(caso, K.NOTIFICAR, K.SISTEMA, 3)
        self.fin_caso[caso["id_tramite"]] = (self.env.now + 0.05, resultado)

    # -- convalidación ----------------------------------------------------------

    def convalidacion(self, caso, az):
        R = self.reglas
        self._log(caso, K.REGISTRAR, K.ESTUDIANTE, caso["registro"], en_calendario=True)
        yield self.env.timeout(max(0, a_habiles(caso["registro"]) - self.env.now))
        externo = caso["origen"] == "Traslado externo"
        med_rev = 0.35 + 0.05 * caso["n_cursos"]
        revisar = lambda p, pr: self.ciclo_secretaria(caso, az, K.REVISAR_EXP, K.OBSERVAR_EXP,  # noqa: E731
                                                       med_rev, p, pr)
        pago = lambda: self.ciclo_tesoreria(caso, az, K.VERIFICAR_PAGO, K.OBSERVAR_PAGO,  # noqa: E731
                                            K.PAGAR, 0.30, 3.0, 0.10)
        directo = az.u("desvio_directo") < 0.03

        if R.pago_al_inicio:
            ok = yield from self.en_paralelo(revisar(0.20, 0.06) if not directo else _nada(self.env),
                                             pago())
        else:
            ok = True if directo else (yield from revisar(0.20, 0.06))
        if not ok:
            return self.fin_caso.setdefault(caso["id_tramite"], (self.env.now, "Archivado"))

        vuelta = 0
        while True:
            yield from self.atender(caso, az, self.dir[caso["carrera"]], K.EVALUAR, K.DIRECCION,
                                    min(2.6, az.lognormal("dur_dir", 0.18 * caso["n_cursos"], 0.45)),
                                    carrera=caso["carrera"])
            p = (0.25 if externo else 0.08) if vuelta == 0 else 0.04
            if az.u(f"obs_dir_{vuelta}") >= p:
                break
            self.instante(caso, K.OBSERVAR_SIL, K.DIRECCION)
            ok = yield from self.estudiante(caso, az, K.SUBSANAR, 2.5, 0.9, 0.07)
            if ok and not R.observacion_a_direccion:
                ok = yield from revisar(0.06, 0.06)
            if not ok:
                return self.fin_caso.setdefault(caso["id_tramite"], (self.env.now, "Archivado"))
            vuelta += 1

        yield from self.atender(caso, az, self.sec, K.EMITIR, K.SECRETARIA,
                                az.lognormal("dur_emitir", 0.3, 0.4))
        yield from self.esperar_firma(caso)

        sin_pago = not R.pago_al_inicio and az.u("desvio_sin_pago") < 0.04
        if not R.pago_al_inicio and not sin_pago:
            ok = yield from pago()
            if not ok:
                return self.fin_caso.setdefault(caso["id_tramite"], (self.env.now, "Archivado"))
        yield from self.atender(caso, az, self.reg, K.REGISTRAR_CONV, K.REGISTROS,
                                az.lognormal("dur_reg", 0.25 + 0.08 * caso["n_cursos"], 0.4),
                                prioridad=0)
        if sin_pago and az.u("pago_tardio") < 0.5:
            yield from self.atender(caso, az, self.tes, K.VERIFICAR_PAGO, K.TESORERIA,
                                    az.lognormal("dur_tes", 0.1, 0.4))
        self.cerrar(caso, "Atendido")

    # -- retiro -----------------------------------------------------------------

    def retiro(self, caso, az):
        R = self.reglas
        limite = K.semestre_de(caso["registro"]).limite_retiro
        self._log(caso, K.REGISTRAR, K.ESTUDIANTE, caso["registro"], en_calendario=True)
        yield self.env.timeout(max(0, a_habiles(caso["registro"]) - self.env.now))
        tarde = caso["registro"] > limite
        revisar = self.ciclo_secretaria(caso, az, K.REVISAR_SOL, K.OBSERVAR_SOL, 0.15,
                                        0.0 if tarde else 0.08, 0.03)
        deuda = lambda: self.ciclo_tesoreria(caso, az, K.VERIFICAR_DEUDA, K.OBSERVAR_DEUDA,  # noqa: E731
                                             K.PAGAR_DEUDA, 0.18, 2.0, 0.15)
        if R.pago_al_inicio and not tarde:
            ok = yield from self.en_paralelo(revisar, deuda())
        else:
            ok = yield from revisar
        if tarde:
            self.instante(caso, K.RECHAZAR_EXT, K.SECRETARIA)
            return self.cerrar(caso, "Rechazado")
        if not ok:
            return self.fin_caso.setdefault(caso["id_tramite"], (self.env.now, "Archivado"))

        pasa_dir = caso["becado"] or not R.visto_bueno_solo_becados
        if pasa_dir and az.u("desvio_sin_vb") >= 0.02:
            yield from self.atender(caso, az, self.dir_ret[caso["carrera"]], K.VISTO_BUENO,
                                    K.DIRECCION, az.lognormal("dur_vb", 0.15, 0.5),
                                    carrera=caso["carrera"], retiro=True)
            if az.u("rechazo_dir") < (0.09 if caso["becado"] else 0.008):
                self.instante(caso, K.RECHAZAR_DIR, K.DIRECCION)
                return self.cerrar(caso, "Rechazado")

        if not R.pago_al_inicio:
            ok = yield from deuda()
            if not ok:
                return self.fin_caso.setdefault(caso["id_tramite"], (self.env.now, "Archivado"))

        with self.reg.request(priority=0) as r:
            yield r
            vencido = a_calendario(self.env.now) > limite
            if vencido:
                yield self.env.timeout(az.lognormal("dur_dev", 0.05, 0.3))
                self._log(caso, K.DEVOLVER_PLAZO, K.REGISTROS, self.env.now)
        if vencido:
            yield from self.atender(caso, az, self.sec, K.EMITIR_EXCEPCION, K.SECRETARIA,
                                    az.lognormal("dur_exc", 0.4, 0.4))
            yield from self.esperar_firma(caso)
        yield from self.atender(caso, az, self.reg, K.APROBAR_RETIRO, K.REGISTROS,
                                az.lognormal("dur_apr", 0.1, 0.4), prioridad=0)
        self.cerrar(caso, "Atendido")


def _nada(env):
    yield env.timeout(0)
    return True


def simular(casos: pd.DataFrame, reglas: K.Reglas = K.Reglas(), seed: int = 16) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Corre el proceso sobre los casos. Devuelve (eventos, fin de cada caso) sin cortar."""
    env = simpy.Environment(initial_time=a_habiles(datetime(2026, 1, 1)))
    uni = Universidad(env, reglas, seed)

    def lanzar(caso, az):
        yield env.timeout(max(0, a_habiles(caso["registro"]) - env.now - 1e-6))
        proc = uni.convalidacion if caso["tipo"] == K.CONVALIDACION else uni.retiro
        yield from proc(caso, az)

    for idx, caso in enumerate(casos.to_dict("records")):
        env.process(lanzar(caso, Azar(seed, idx)))
    env.run(until=a_habiles(FIN_SIMULACION))

    ev = pd.DataFrame(uni.eventos, columns=["id_tramite", "actividad", "area", "usuario",
                                            "inicio", "fin", "en_calendario"])
    cal = ev["en_calendario"].to_numpy()
    fin = pd.Series(pd.NaT, index=ev.index, dtype="datetime64[ns]")
    fin[cal] = pd.to_datetime(ev.loc[cal, "fin"])
    fin[~cal] = a_calendario(ev.loc[~cal, "fin"].astype(float).to_numpy())
    ini = pd.Series(pd.NaT, index=ev.index, dtype="datetime64[ns]")
    tiene = ev["inicio"].notna()
    ini[tiene] = a_calendario(ev.loc[tiene, "inicio"].astype(float).to_numpy())
    ev = ev.assign(inicio=ini, fin=fin.dt.round("s")).drop(columns="en_calendario")
    ev = ev.sort_values(["id_tramite", "fin"], kind="stable").reset_index(drop=True)

    fines = pd.DataFrame([(k, v[0], v[1]) for k, v in uni.fin_caso.items()],
                         columns=["id_tramite", "fin_h", "resultado"])
    fines["fin"] = a_calendario(fines["fin_h"].to_numpy())
    return ev, fines.drop(columns="fin_h")


# --------------------------------------------------------------------------
# Export con el formato del sistema
# --------------------------------------------------------------------------

def exportar(casos: pd.DataFrame, eventos: pd.DataFrame, destino: Path, seed: int) -> None:
    """Escribe los dos CSV tal como salen del sistema: cortados al día del export y con ruido."""
    rng = np.random.default_rng(seed + 3)
    carpeta = destino / "exports"
    carpeta.mkdir(parents=True, exist_ok=True)
    ev = eventos[eventos["fin"] <= K.CORTE].copy()
    # el sistema guarda dos veces algunos eventos cuando el usuario hace doble clic
    dup = ev.sample(frac=0.012, random_state=int(rng.integers(1e9)))
    ev = pd.concat([ev, dup]).sort_values(["id_tramite", "fin"], kind="stable")
    fmt = "%d/%m/%Y %H:%M:%S"
    salida = pd.DataFrame({
        "NRO_TRAMITE": ev["id_tramite"],
        "ACTIVIDAD": ev["actividad"].str.upper(),
        "AREA": ev["area"],
        "USUARIO": ev["usuario"].str.upper(),
        "F_INICIO": ev["inicio"].dt.strftime(fmt).fillna(""),
        "F_FIN": ev["fin"].dt.strftime(fmt),
    })
    salida.to_csv(carpeta / "log_tramites.csv", index=False, sep=";", encoding="utf-8-sig")

    c = casos[casos["registro"] <= K.CORTE]
    pd.DataFrame({
        "NRO_TRAMITE": c["id_tramite"],
        "TIPO": c["tipo"],
        "COD_ALUMNO": c["codigo_alumno"],
        "ALUMNO": c["nombre_alumno"].str.upper(),
        "CARRERA": c["carrera"],
        "SEDE": c["sede"],
        "NRO_CURSOS": np.where(c["tipo"] == K.CONVALIDACION, c["n_cursos"].astype(str), ""),
        "ORIGEN": c["origen"].fillna(""),
        "BECA": np.where(c["becado"], "SI", "NO"),
        "F_REGISTRO": c["registro"].dt.strftime(fmt),
    }).to_csv(carpeta / "tramites.csv", index=False, sep=";", encoding="utf-8-sig")


def generar(destino: Path = DESTINO, escala: float = 1.0, seed: int = 16) -> Path:
    destino = Path(destino)
    casos = generar_casos(escala, seed)
    eventos, fines = simular(casos, K.Reglas(), seed)
    exportar(casos, eventos, destino, seed)
    verdad = destino / "verdad"
    verdad.mkdir(parents=True, exist_ok=True)
    casos.merge(fines, on="id_tramite", how="left").to_parquet(verdad / "casos.parquet", index=False)
    eventos.to_parquet(verdad / "eventos.parquet", index=False)
    return destino / "exports"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", type=Path, default=DESTINO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=16)
    a = ap.parse_args()
    print(generar(a.destino, a.escala, a.seed))
