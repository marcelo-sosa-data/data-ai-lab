"""
Simulación de escenarios por remuestreo del log.

Cada trámite del periodo de prueba se vuelve a recorrer paso a paso con las
reglas de un escenario. El tiempo de cada paso (espera más atención, en
horas hábiles) se sortea de lo observado en el periodo de estimación para
la misma actividad, la misma actividad anterior y un nivel de carga
parecido. Las probabilidades de observación, falta de pago y abandono, y
las demoras del estudiante, también salen del log. La firma no se sortea:
se espera el siguiente turno del decano, con la tasa de semanas sin firma
que muestra el log.

Supuesto fuerte: la espera en un área no cambia cuando el escenario le
quita trabajo. Si un escenario descarga a Dirección, la simulación no le
reconoce esa mejora en los otros trámites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import numpy as np
import pandas as pd

from . import catalogos as K
from .calendario import HORAS_DIA, ORIGEN, a_calendario, a_habiles, es_habil

VENTANA_CARGA = pd.Timedelta(days=14)
MIN_MUESTRAS = 15


@dataclass
class Parametros:
    tiempos: dict = field(default_factory=dict)       # clave -> horas hábiles
    p: dict = field(default_factory=dict)              # probabilidades de ruta
    demoras: dict = field(default_factory=dict)        # actividad del estudiante -> días calendario
    cortes_carga: dict = field(default_factory=dict)   # tipo -> límites de terciles
    registros: dict = field(default_factory=dict)      # tipo -> fechas de registro ordenadas
    firma_dias: tuple = (4,)
    firma_hora: float = 10.0
    firma_salto: float = 0.0
    firma_demora_h: np.ndarray = field(default_factory=lambda: np.array([0.0]))


# --------------------------------------------------------------------------
# Estimación
# --------------------------------------------------------------------------

def _carga(registros: np.ndarray, momentos: pd.Series) -> np.ndarray:
    """Trámites del mismo tipo registrados en los 14 días previos a cada momento."""
    m = momentos.to_numpy(dtype="datetime64[ns]")
    return (np.searchsorted(registros, m, side="right")
            - np.searchsorted(registros, m - VENTANA_CARGA.to_timedelta64(), side="right"))


def _nivel(carga, cortes) -> np.ndarray:
    return np.searchsorted(cortes, carga, side="right")


def _proporcion(exito: pd.Series) -> float:
    return float(exito.mean()) if len(exito) else 0.0


def ausencias_direccion(ev_t: pd.DataFrame, tramites: pd.DataFrame, min_dias: int = 5) -> pd.DataFrame:
    """
    Tramos de `min_dias` o más días hábiles seguidos en que un director no registró
    ninguna actividad teniendo trámites de su carrera en bandeja (vacaciones, licencia).

    `normal_desde` es la primera semana después de la ausencia en que la espera
    mediana en esa Dirección vuelve a 1.5 veces la de las cuatro semanas previas:
    hasta ahí dura la cola que dejó la ausencia.
    """
    ev = ev_t.merge(tramites[["id_tramite", "carrera"]], on="id_tramite")
    d = ev[(ev["area"] == K.DIRECCION) & ev["fin_anterior"].notna()]
    filas = []
    for carrera, g in d.groupby("carrera"):
        activos = set(g["fin"].dt.date)
        dias = [x.date() for x in pd.date_range(g["fin"].min().normalize(), g["fin"].max().normalize())
                if es_habil(x.date())]
        racha = []
        for dia in dias + [None]:
            if dia is not None and dia not in activos:
                racha.append(dia)
                continue
            if len(racha) >= min_dias:
                en_espera = ((g["fin_anterior"].dt.date <= racha[0]) & (g["fin"].dt.date > racha[-1])).sum()
                if en_espera:
                    filas.append({"carrera": carrera, "desde": racha[0], "hasta": racha[-1],
                                  "dias_habiles": len(racha), "tramites_en_espera": int(en_espera),
                                  "normal_desde": _vuelta_a_lo_normal(g, racha[0], racha[-1])})
            racha = []
    return pd.DataFrame(filas, columns=["carrera", "desde", "hasta", "dias_habiles",
                                        "tramites_en_espera", "normal_desde"])


def _vuelta_a_lo_normal(g: pd.DataFrame, desde, hasta):
    llegada = g["fin_anterior"].dt.date
    antes = g.loc[(llegada < desde) & (llegada >= desde - timedelta(days=28)), "total_h"]
    base = antes.median() if len(antes) >= 5 else g["total_h"].median()
    semana = hasta + timedelta(days=1)
    while semana <= g["fin"].max().date():
        s = g.loc[(llegada >= semana) & (llegada < semana + timedelta(days=7)), "total_h"]
        if len(s) == 0 or s.median() <= 1.5 * base:
            return semana
        semana += timedelta(days=7)
    return semana


def estimar(ev_t: pd.DataFrame, tramites: pd.DataFrame, desde, hasta,
            sin_ausencias: bool = True) -> Parametros:
    """
    Parámetros a partir de los trámites registrados entre `desde` y `hasta`.
    Con `sin_ausencias`, las esperas en Dirección que llegan durante una ausencia
    del director o mientras se despacha la cola que dejó no entran a la muestra:
    el periodo que se simula no tiene ausencias.
    """
    par = Parametros()
    for tipo, g in tramites.groupby("tipo"):
        par.registros[tipo] = np.sort(g["registro"].to_numpy(dtype="datetime64[ns]"))

    ids = tramites.loc[tramites["registro"].between(desde, hasta), ["id_tramite", "tipo", "origen",
                                                                     "becado"]]
    ev = ev_t.merge(ids, on="id_tramite").sort_values(["id_tramite", "orden"])
    ev["anterior"] = ev.groupby("id_tramite")["actividad"].shift()
    ev["siguiente"] = ev.groupby("id_tramite")["actividad"].shift(-1)
    ev["vez"] = ev.groupby(["id_tramite", "actividad"]).cumcount()

    # tiempos de las áreas, por nivel de carga cuando el trámite llegó al área
    pasos = ev[ev["total_h"].notna() & ~ev["area"].isin([K.ESTUDIANTE, K.SISTEMA])
               & ~ev["actividad"].isin(K.OBSERVACIONES | {K.FIRMAR, K.ARCHIVAR, K.RECHAZAR_EXT,
                                                          K.RECHAZAR_DIR})].copy()
    if sin_ausencias:
        aus = ausencias_direccion(ev_t, tramites)
        pasos = pasos.merge(tramites[["id_tramite", "carrera"]], on="id_tramite")
        cruza = np.zeros(len(pasos), dtype=bool)
        for a in aus.itertuples():
            cruza |= ((pasos["area"] == K.DIRECCION) & (pasos["carrera"] == a.carrera)
                      & (pasos["fin_anterior"].dt.date < a.normal_desde)
                      & (pasos["fin"].dt.date >= a.desde)).to_numpy()
        pasos = pasos[~cruza]
    pasos["carga"] = 0
    for tipo in par.registros:
        s = pasos["tipo"] == tipo
        pasos.loc[s, "carga"] = _carga(par.registros[tipo], pasos.loc[s, "fin_anterior"])
        par.cortes_carga[tipo] = np.quantile(pasos.loc[s, "carga"], [1 / 3, 2 / 3])
        pasos.loc[s, "nivel"] = _nivel(pasos.loc[s, "carga"], par.cortes_carga[tipo])
    for claves in (["tipo", "actividad", "nivel"], ["tipo", "actividad"]):
        for k, g in pasos.groupby(claves):
            if len(g) >= MIN_MUESTRAS or len(claves) == 2:
                par.tiempos[tuple(k)] = g["total_h"].to_numpy()

    # probabilidades de ruta
    def p_obs(act, obs, primera=True, filtro=None):
        g = ev[(ev["actividad"] == act) & ((ev["vez"] == 0) if primera else (ev["vez"] > 0))]
        if filtro is not None:
            g = g[filtro(g)]
        return _proporcion(g["siguiente"] == obs)

    P = par.p
    P["obs_exp_1"], P["obs_exp_n"] = p_obs(K.REVISAR_EXP, K.OBSERVAR_EXP), p_obs(K.REVISAR_EXP, K.OBSERVAR_EXP, False)
    for origen in ("Traslado externo", "Cambio de carrera"):
        P[f"obs_sil_1_{origen}"] = p_obs(K.EVALUAR, K.OBSERVAR_SIL, filtro=lambda g, o=origen: g["origen"] == o)
    P["obs_sil_n"] = p_obs(K.EVALUAR, K.OBSERVAR_SIL, False)
    P["no_pago"] = p_obs(K.VERIFICAR_PAGO, K.OBSERVAR_PAGO)
    P["obs_sol_1"], P["obs_sol_n"] = p_obs(K.REVISAR_SOL, K.OBSERVAR_SOL), p_obs(K.REVISAR_SOL, K.OBSERVAR_SOL, False)
    P["deuda"] = p_obs(K.VERIFICAR_DEUDA, K.OBSERVAR_DEUDA)
    for b in (True, False):
        P[f"rechazo_dir_{b}"] = p_obs(K.VISTO_BUENO, K.RECHAZAR_DIR, filtro=lambda g, b=b: g["becado"] == b)

    por_caso = ev.groupby("id_tramite")["actividad"].agg(set)
    tipo_caso = ids.set_index("id_tramite")["tipo"]
    conv = por_caso[tipo_caso.reindex(por_caso.index) == K.CONVALIDACION]
    reg_conv = conv[conv.map(lambda s: K.REGISTRAR_CONV in s)]
    # desvíos del proceso actual: se reproducen en el escenario actual y se eliminan en los otros
    primeros = ev[ev["vez"] == 0].pivot_table(index="id_tramite", columns="actividad", values="orden")
    if K.EVALUAR in primeros and K.REVISAR_EXP in primeros:
        e, r = primeros[K.EVALUAR].dropna(), primeros[K.REVISAR_EXP]
        P["directo"] = _proporcion(r.reindex(e.index).isna() | (r.reindex(e.index) > e))
    sig_pago = ev[(ev["actividad"] == K.VERIFICAR_PAGO) & (ev["siguiente"] != K.OBSERVAR_PAGO)]
    pago_ok = sig_pago.groupby("id_tramite")["orden"].min()
    reg = ev[ev["actividad"] == K.REGISTRAR_CONV].groupby("id_tramite")["orden"].min()
    sin = reg.index[pago_ok.reindex(reg.index).isna() | (pago_ok.reindex(reg.index) > reg)]
    P["sin_pago"] = len(sin) / max(len(reg_conv), 1)
    P["pago_despues"] = _proporcion(pago_ok.reindex(sin).notna())
    ret = por_caso[tipo_caso.reindex(por_caso.index) == K.RETIRO]
    apr = ret[ret.map(lambda s: K.APROBAR_RETIRO in s)]
    P["sin_vb"] = _proporcion(apr.map(lambda s: K.VISTO_BUENO not in s))

    # respuestas del estudiante: demora en días calendario y abandono
    for obs, resp, clave in ((K.OBSERVAR_EXP, K.SUBSANAR, "subsanar"), (K.OBSERVAR_SIL, K.SUBSANAR, "subsanar"),
                             (K.OBSERVAR_SOL, K.SUBSANAR, "subsanar"), (K.OBSERVAR_PAGO, K.PAGAR, "pagar"),
                             (K.OBSERVAR_DEUDA, K.PAGAR_DEUDA, "deuda")):
        o = ev[ev["actividad"] == obs]
        par.demoras.setdefault(clave, []).extend(
            ev.loc[(ev["actividad"] == resp) & (ev["anterior"] == obs), "total_dias_cal"].dropna().tolist())
        P.setdefault(f"n_obs_{clave}", 0)
        P.setdefault(f"n_aband_{clave}", 0)
        P[f"n_obs_{clave}"] += len(o)
        P[f"n_aband_{clave}"] += int((o["siguiente"] == K.ARCHIVAR).sum())
    for clave in ("subsanar", "pagar", "deuda"):
        par.demoras[clave] = np.array(par.demoras[clave])
        P[f"abandono_{clave}"] = P.pop(f"n_aband_{clave}") / max(P.pop(f"n_obs_{clave}"), 1)

    # turnos de firma: días y hora en que firma el decano, y semanas sin firma
    firmas = ev.loc[ev["actividad"] == K.FIRMAR, "fin"]
    dias = firmas.dt.normalize().drop_duplicates()
    dia_sem = dias.dt.weekday.value_counts(normalize=True)
    par.firma_dias = tuple(sorted(dia_sem[dia_sem > 0.1].index))
    # el turno empieza a la hora de las primeras firmas; las demás se reparten después
    hora = firmas.dt.hour + firmas.dt.minute / 60
    par.firma_hora = float(np.floor(hora.quantile(0.02) * 2) / 2)
    rango = pd.date_range(firmas.min().normalize(), firmas.max().normalize(), freq="D")
    posibles = [d for d in rango if d.weekday() in par.firma_dias and es_habil(d.date())]
    par.firma_salto = 1 - len(set(dias) & set(posibles)) / max(len(posibles), 1)
    turno = firmas.dt.normalize() + pd.to_timedelta(par.firma_hora, unit="h")
    par.firma_demora_h = ((firmas - turno).dt.total_seconds() / 3600).clip(lower=0).to_numpy()
    return par


# --------------------------------------------------------------------------
# Recorrido de un trámite
# --------------------------------------------------------------------------

class Reloj:
    """Conversiones entre horas hábiles y calendario con tablas precalculadas (rápidas)."""

    def __init__(self, par: Parametros, hasta: pd.Timestamp):
        self.h_max = float(a_habiles(hasta))
        self.h_grid = np.arange(0, self.h_max, 1 / 60)
        self.cal_grid = _dias_desde_origen(a_calendario(self.h_grid))
        cal15 = pd.date_range(pd.Timestamp(ORIGEN), hasta, freq="15min")
        self.c15 = _dias_desde_origen(cal15)
        self.h15 = a_habiles(cal15)
        horas = np.arange(0, int(self.h_max) + 1)
        momentos = pd.Series(a_calendario(horas.astype(float)))
        self.nivel = {tipo: _nivel(_carga(reg, momentos), par.cortes_carga[tipo])
                      for tipo, reg in par.registros.items() if tipo in par.cortes_carga}

    def calendario(self, h: float) -> float:
        """Días desde ORIGEN (con fracción) para una hora hábil."""
        return float(np.interp(h, self.h_grid, self.cal_grid))

    def habiles(self, dias: float) -> float:
        return float(np.interp(dias, self.c15, self.h15))

    def nivel_carga(self, tipo: str, h: float) -> int:
        n = self.nivel[tipo]
        return int(n[min(int(h), len(n) - 1)])


def _dias_desde_origen(fechas) -> np.ndarray:
    return (pd.DatetimeIndex(fechas) - pd.Timestamp(ORIGEN)).total_seconds().to_numpy() / 86400


class Recorrido:
    def __init__(self, par: Parametros, reglas: K.Reglas, actual: bool, rng: np.random.Generator,
                 hasta: pd.Timestamp, reloj: Reloj):
        self.par, self.R, self.actual, self.rng, self.reloj = par, reglas, actual, rng, reloj
        ini = pd.Timestamp("2026-01-01")
        self.turnos = self._turnos(ini, hasta, par.firma_dias if actual else reglas.dias_firma)
        self._h_limite = {s.limite_retiro: float(a_habiles(s.limite_retiro)) for s in K.SEMESTRES}

    def _turnos(self, ini, fin, dias):
        fechas = [d for d in pd.date_range(ini, fin, freq="D")
                  if d.weekday() in dias and es_habil(d.date())]
        return a_habiles([d + pd.Timedelta(hours=self.par.firma_hora) for d in fechas])

    def u(self) -> float:
        return float(self.rng.random())

    def sorteo(self, arr: np.ndarray) -> float:
        return float(arr[self.rng.integers(len(arr))])

    def paso(self, tipo, act, t):
        nivel = self.reloj.nivel_carga(tipo, t)
        T = self.par.tiempos
        for k in ((tipo, act, nivel), (tipo, act)):
            if k in T:
                return t + self.sorteo(T[k])
        raise KeyError(f"No hay tiempos para {tipo} / {act}")

    def estudiante(self, clave, t):
        """Devuelve la hora hábil en que responde, o None si abandona."""
        if self.u() < self.par.p[f"abandono_{clave}"]:
            return None
        return self.reloj.habiles(self.reloj.calendario(t) + self.sorteo(self.par.demoras[clave]))

    def firma(self, t):
        i = int(np.searchsorted(self.turnos, t, side="right"))
        while i < len(self.turnos) - 1 and self.u() < self.par.firma_salto:
            i += 1
        return float(self.turnos[min(i, len(self.turnos) - 1)]) + self.sorteo(self.par.firma_demora_h)

    # -- ciclos -----------------------------------------------------------------

    def ciclo_revision(self, tipo, act, p, p_rep, t):
        """Revisión con observaciones y subsanación hasta que pasa. None si el estudiante abandona."""
        while True:
            t = self.paso(tipo, act, t)
            if self.u() >= p:
                return t
            t = self.estudiante("subsanar", t)
            if t is None:
                return None
            p = p_rep

    def ciclo_pago(self, tipo, act, p_no, clave, t):
        t = self.paso(tipo, act, t)
        if self.u() >= p_no:
            return t
        t = self.estudiante(clave, t)
        return None if t is None else self.paso(tipo, act, t)

    # -- trámites ---------------------------------------------------------------

    def convalidacion(self, caso) -> dict:
        P, R, tipo = self.par.p, self.R, K.CONVALIDACION
        t0 = caso["_h"]
        res = {"evaluaciones": 0, "revisiones": 0}
        archivado = {**res, "estado": "Archivado", "fin": None}
        directo = self.actual and self.u() < P.get("directo", 0)

        def revision(t, primera=True):
            res["revisiones"] += 1
            return self.ciclo_revision(tipo, K.REVISAR_EXP, P["obs_exp_1"] if primera else P["obs_exp_n"],
                                       P["obs_exp_n"], t)

        def pago(t):
            return self.ciclo_pago(tipo, K.VERIFICAR_PAGO, P["no_pago"], "pagar", t)

        t = t0 if directo else revision(t0)
        if R.pago_al_inicio:
            t_pago = pago(t0)
            t = None if t is None or t_pago is None else max(t, t_pago)
        if t is None:
            return {**archivado, **res}

        p = P[f"obs_sil_1_{caso['origen']}"]
        while True:
            t = self.paso(tipo, K.EVALUAR, t)
            res["evaluaciones"] += 1
            if self.u() >= p:
                break
            t = self.estudiante("subsanar", t)
            if t is not None and not R.observacion_a_direccion:
                t = revision(t, primera=False)
            if t is None:
                return {**archivado, **res}
            p = P["obs_sil_n"]

        t = self.firma(self.paso(tipo, K.EMITIR, t))
        sin_pago = self.actual and self.u() < P.get("sin_pago", 0)
        if not R.pago_al_inicio and not sin_pago:
            t = pago(t)
            if t is None:
                return {**archivado, **res, "archivado_tras_firma": True}
        t = self.paso(tipo, K.REGISTRAR_CONV, t)
        return {**res, "estado": "Atendido", "fin": t + 0.05}

    def retiro(self, caso) -> dict:
        P, R, tipo = self.par.p, self.R, K.RETIRO
        limite = K.semestre_de(caso["registro"]).limite_retiro
        t0 = caso["_h"]
        res = {"excepcion": False, "direccion": False}
        archivado = {**res, "estado": "Archivado", "fin": None}
        if caso["registro"] > limite:
            return {**res, "estado": "Rechazado", "fin": self.paso(tipo, K.REVISAR_SOL, t0)}

        def deuda(t):
            return self.ciclo_pago(tipo, K.VERIFICAR_DEUDA, P["deuda"], "deuda", t)

        t = self.ciclo_revision(tipo, K.REVISAR_SOL, P["obs_sol_1"], P["obs_sol_n"], t0)
        if R.pago_al_inicio:
            t_deuda = deuda(t0)
            t = None if t is None or t_deuda is None else max(t, t_deuda)
        if t is None:
            return archivado

        pasa = caso["becado"] or not R.visto_bueno_solo_becados
        if pasa and not (self.actual and self.u() < P.get("sin_vb", 0)):
            t = self.paso(tipo, K.VISTO_BUENO, t)
            res["direccion"] = True
            if self.u() < P[f"rechazo_dir_{bool(caso['becado'])}"]:
                return {**res, "estado": "Rechazado", "fin": t}
        if not R.pago_al_inicio:
            t = deuda(t)
            if t is None:
                return {**archivado, **res}

        t = self.paso(tipo, K.APROBAR_RETIRO, t)
        if t > self._h_limite[limite]:
            # Registros lo devuelve: resolución de excepción, firma y recién se aprueba
            res["excepcion"] = True
            t = self.firma(self.paso(tipo, K.EMITIR_EXCEPCION, t))
            t = self.paso(tipo, K.APROBAR_RETIRO, t)
        return {**res, "estado": "Atendido", "fin": t + 0.05}


def simular(par: Parametros, casos: pd.DataFrame, reglas: K.Reglas, actual: bool,
            replicas: int = 30, seed: int = 0) -> pd.DataFrame:
    """Una fila por trámite y réplica con el estado, la hora de fin y las marcas del recorrido."""
    filas = []
    hasta = casos["registro"].max() + pd.Timedelta(days=200)
    reloj = Reloj(par, hasta)
    registros = casos.assign(_h=a_habiles(casos["registro"])).to_dict("records")
    for r in range(replicas):
        rec = Recorrido(par, reglas, actual, np.random.default_rng([seed, r]), hasta, reloj)
        for c in registros:
            out = rec.convalidacion(c) if c["tipo"] == K.CONVALIDACION else rec.retiro(c)
            filas.append({"replica": r, "id_tramite": c["id_tramite"], "tipo": c["tipo"],
                          "registro": c["registro"], **out})
    df = pd.DataFrame(filas)
    ok = df["fin"].notna()
    df["fin_fecha"] = pd.NaT
    df.loc[ok, "fin_fecha"] = a_calendario(df.loc[ok, "fin"].astype(float).to_numpy())
    df["fin_fecha"] = pd.to_datetime(df["fin_fecha"])
    df["duracion_dias"] = (df["fin_fecha"] - df["registro"]).dt.total_seconds() / 86400
    df["dias_habiles"] = (df["fin"] - a_habiles(df["registro"])) / HORAS_DIA
    df["fuera_plazo"] = df["dias_habiles"] > df["tipo"].map(K.PLAZO_DIAS)
    return df


def indicadores(df: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """Mediana, p90, % fuera de plazo y % con excepción por tipo (y por réplica si la hay)."""
    por = (por or []) + ["tipo"]
    filas = []
    for k, g in df.groupby(por):
        a = g[g["estado"] == "Atendido"]
        k = k if isinstance(k, tuple) else (k,)
        fila = dict(zip(por, k))
        fila.update({
            "atendidos": len(a),
            "mediana_dias": a["duracion_dias"].median(),
            "p90_dias": a["duracion_dias"].quantile(0.9),
            "pct_fuera_plazo": a["fuera_plazo"].mean(),
            "pct_excepcion": g["excepcion"].astype(float).mean() if "excepcion" in g and
            fila["tipo"] == K.RETIRO else np.nan,
        })
        filas.append(fila)
    return pd.DataFrame(filas)


def resumir_replicas(ind: pd.DataFrame) -> pd.DataFrame:
    """Promedio de las réplicas y rango del 5% al 95%."""
    metr = ["mediana_dias", "p90_dias", "pct_fuera_plazo", "pct_excepcion"]
    g = ind.groupby("tipo")
    res = g[metr].mean()
    for m in metr:
        res[f"{m}_p05"] = g[m].quantile(0.05)
        res[f"{m}_p95"] = g[m].quantile(0.95)
    return res.reset_index()
