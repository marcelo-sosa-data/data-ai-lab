"""
Genera una semana de eventos de pedidos de Wayki, una app de delivery
ficticia que opera en 12 zonas de Lima.

Cada pedido pasa por la cola de su zona: entra cuando el restaurante lo
acepta, espera a que un motorizado lo tome y, si la espera supera la
paciencia del cliente, se cancela. Lo que sale son eventos tal como los
emiten las apps (creado, asignado, entregado, cancelado), con dos
problemas de la vida real:

  - llegan tarde: la app del motorizado sin señal guarda el evento y lo
    manda al reconectar; en SJL, Ate y Los Olivos pasa más seguido
  - llegan repetidos: si la app no recibe confirmación, reintenta con el
    mismo id de evento

Encima de la operación normal hay incidentes sembrados (pocos motorizados
conectados, picos de demanda por un concierto o una promoción). Quedan en
incidentes.parquet como verdad para medir cuánto tarda cada proceso en
detectarlos.

Uso:
    python datos/generar_datos.py                 # semana completa (~10 s)
    python datos/generar_datos.py --escala 0.2    # versión chica para pruebas
"""

from __future__ import annotations

import argparse
import heapq
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DIR_DEFECTO = Path(__file__).parent
INICIO_SEMANA = datetime(2026, 10, 5)          # lunes
DIAS = 7
HORA_APERTURA, HORA_CIERRE = 10, 24            # la app opera de 10:00 a 23:59
DEMORA_ASIGNACION_MIN = 6                      # umbral operativo de Wayki

# zona, pedidos por día (base), calidad de señal (0 buena, 2 mala)
ZONAS = [
    ("Miraflores", 980, 0),
    ("San Isidro", 760, 0),
    ("Surco", 1150, 0),
    ("San Borja", 620, 0),
    ("Barranco-Chorrillos", 690, 1),
    ("Jesús María-Lince", 720, 0),
    ("San Miguel-Pueblo Libre", 810, 1),
    ("Los Olivos", 870, 2),
    ("SMP", 640, 1),
    ("SJL", 930, 2),
    ("Ate", 560, 2),
    ("La Molina", 540, 1),
]

FACTOR_DIA = [0.86, 0.84, 0.90, 0.95, 1.18, 1.30, 1.12]    # lun..dom

# incidentes: día (0 = lunes), zona, inicio, minutos, causa, factor de
# motorizados disponibles, factor de demanda
INCIDENTES = [
    (0, "Surco", "19:40", 45, "pocos motorizados conectados", 0.30, 1.0),
    (1, "SJL", "13:05", 35, "cierre de vía en Próceres", 0.30, 1.0),
    (2, "Jesús María-Lince", "20:10", 55, "concierto en el estadio", 0.80, 2.2),
    (3, "Miraflores", "12:30", 30, "pocos motorizados conectados", 0.40, 1.0),
    (3, "Ate", "21:00", 40, "caída de la app de motorizados", 0.20, 1.0),
    (4, "Los Olivos", "20:25", 50, "promoción 2x1 en pollerías", 0.85, 2.0),
    (4, "San Borja", "19:15", 25, "pocos motorizados conectados", 0.55, 1.0),
    (5, "Surco", "13:20", 40, "promoción 2x1 en pollerías", 0.80, 1.9),
    (5, "SMP", "21:30", 45, "lluvia ligera y pocos motorizados", 0.35, 1.3),
    (6, "Barranco-Chorrillos", "14:00", 35, "pocos motorizados conectados", 0.35, 1.0),
    (6, "San Isidro", "20:40", 30, "cierre de vía en Javier Prado", 0.40, 1.0),
]


def curva_hora(minuto_del_dia: np.ndarray) -> np.ndarray:
    """Peso relativo de la demanda por minuto: almuerzo y cena."""
    h = minuto_del_dia / 60
    almuerzo = 1.25 * np.exp(-0.5 * ((h - 13.4) / 1.0) ** 2)
    cena = 1.55 * np.exp(-0.5 * ((h - 20.6) / 1.3) ** 2)
    return 0.18 + almuerzo + cena


def _demora_llegada(rng, n: int, senal: int, app: str) -> np.ndarray:
    """Segundos entre que ocurre el evento y que llega al broker."""
    if app == "cliente":
        p_tarde, p_muy_tarde = 0.015, 0.002
    else:  # app del motorizado
        p_tarde, p_muy_tarde = [(0.04, 0.006), (0.07, 0.012), (0.12, 0.025)][senal]
    u = rng.random(n)
    normal = rng.exponential(1.2, n)                       # segundos
    tarde = rng.uniform(15, 240, n)                        # sin señal un rato
    muy_tarde = rng.uniform(300, 2400, n)                  # reconecta mucho después
    return np.where(u < p_muy_tarde, muy_tarde, np.where(u < p_muy_tarde + p_tarde, tarde, normal))


def _simular_zona(rng, zona: str, base: float, dia: int, escala: float, incidentes):
    """Cola de pedidos de una zona en un día. Devuelve la lista de pedidos."""
    minutos = np.arange(HORA_APERTURA * 60, HORA_CIERRE * 60)
    peso = curva_hora(minutos)
    lam = base * escala * FACTOR_DIA[dia] * peso / peso.sum()

    f_cap = np.ones_like(lam)
    f_dem = np.ones_like(lam)
    for _, z, ini, dur, _, fc, fd in incidentes:
        if z != zona:
            continue
        h, m = map(int, ini.split(":"))
        sel = (minutos >= h * 60 + m) & (minutos < h * 60 + m + dur)
        f_cap[sel] = fc
        f_dem[sel] = fd

    # motorizados que se liberan por minuto: 45% de holgura sobre la demanda
    # esperada, algo menos en horas punta. La oferta no reacciona al pico de
    # un incidente, por eso se calcula sin f_dem
    holgura = 1.45 - 0.10 * (peso / peso.max())
    liberados = rng.poisson(lam * holgura * f_cap)
    # un motorizado libre espera unos minutos en la zona y luego se va a otra
    tope_libres = np.ceil(lam * 6).astype(int) + 2
    llegadas = rng.poisson(lam * f_dem)

    pedidos, por_listos, cola = [], [], deque()
    libres = 0
    fecha = INICIO_SEMANA + timedelta(days=dia)

    def purgar(t):
        while cola and cola[0]["creado"] + cola[0]["paciencia"] <= t:
            q = cola.popleft()
            q["cancelado"] = q["creado"] + q["paciencia"]

    for i, minuto in enumerate(minutos):
        for c in np.sort(minuto + rng.random(llegadas[i])):
            busqueda = rng.lognormal(np.log(1.6), 0.55)      # minutos
            p = {"zona": zona, "creado": c, "listo": c + busqueda,
                 "paciencia": 3 + rng.exponential(13), "asignado": None, "cancelado": None}
            pedidos.append(p)
            heapq.heappush(por_listos, (p["listo"], len(pedidos), p))
        sucesos = [(t, 1, None) for t in minuto + rng.random(liberados[i])]
        while por_listos and por_listos[0][0] < minuto + 1:
            t, _, p = heapq.heappop(por_listos)
            sucesos.append((t, 0, p))
        for t, es_moto, p in sorted(sucesos, key=lambda x: x[0]):
            purgar(t)
            if es_moto:
                if cola:
                    cola.popleft()["asignado"] = t
                else:
                    libres += 1
            elif p["creado"] + p["paciencia"] <= t:
                p["cancelado"] = p["creado"] + p["paciencia"]
            elif libres and not cola:
                libres -= 1
                p["asignado"] = t
            else:
                cola.append(p)
        purgar(minuto + 1)
        libres = min(libres, tope_libres[i])
    for _, _, p in por_listos:
        cola.append(p)
    for q in cola:                                   # lo que quedó al cierre
        q["cancelado"] = q["creado"] + q["paciencia"]
    for p in pedidos:
        p["fecha"] = fecha
    return pedidos


def generar(directorio: str | Path = DIR_DEFECTO, escala: float = 1.0, seed: int = 2026) -> Path:
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    pedidos = []
    for dia in range(DIAS):
        incidentes_dia = [x for x in INCIDENTES if x[0] == dia]
        for zona, base, _ in ZONAS:
            pedidos.extend(_simular_zona(rng, zona, base, dia, escala, incidentes_dia))

    df = pd.DataFrame(pedidos)
    df["pedido_id"] = [f"P{i:07d}" for i in range(1, len(df) + 1)]
    # cancelación espontánea del cliente antes de la asignación (~1%)
    arrep = (rng.random(len(df)) < 0.01) & df["asignado"].notna()
    df.loc[arrep, "cancelado"] = df.loc[arrep, "creado"] + rng.uniform(0.5, 2.5, arrep.sum())
    df.loc[arrep & (df["cancelado"] < df["asignado"]), "asignado"] = np.nan
    df.loc[df["asignado"].notna(), "cancelado"] = np.nan
    entrega = rng.lognormal(np.log(24), 0.28, len(df))
    df["entregado"] = np.where(df["asignado"].notna(), df["asignado"] + entrega, np.nan)

    senal = {z: s for z, _, s in ZONAS}
    base_ts = df["fecha"].astype("datetime64[ns]")

    def _ev(tipo: str, col: str, app: str) -> pd.DataFrame:
        sub = df[df[col].notna()]
        e = pd.DataFrame({
            "pedido_id": sub["pedido_id"].values,
            "zona": sub["zona"].values,
            "tipo": tipo,
            "ts_evento": (base_ts[sub.index] + pd.to_timedelta(sub[col] * 60, unit="s")).values,
            "espera_asignacion_s": ((sub["asignado"] - sub["creado"]) * 60).round(1).values
            if tipo == "asignado" else np.nan,
            "app": app,
        })
        return e

    ev = pd.concat([
        _ev("creado", "creado", "cliente"),
        _ev("asignado", "asignado", "motorizado"),
        _ev("entregado", "entregado", "motorizado"),
        _ev("cancelado", "cancelado", "cliente"),
    ], ignore_index=True)
    ev["ts_evento"] = ev["ts_evento"].dt.floor("ms")

    demora = np.zeros(len(ev))
    for (z, app), idx in ev.groupby(["zona", "app"]).groups.items():
        demora[ev.index.get_indexer(idx)] = _demora_llegada(rng, len(idx), senal[z], app)
    ev["ts_recibido"] = ev["ts_evento"] + pd.to_timedelta(demora, unit="s")
    ev = ev.sort_values(["ts_evento", "pedido_id"]).reset_index(drop=True)
    ev["evento_id"] = [f"E{i:08d}" for i in range(1, len(ev) + 1)]

    # reintentos: mismo evento_id, llega otra vez segundos o minutos después
    dup = ev[rng.random(len(ev)) < 0.025].copy()
    dup["ts_recibido"] = dup["ts_recibido"] + pd.to_timedelta(
        np.where(rng.random(len(dup)) < 0.85, rng.uniform(1, 20, len(dup)),
                 rng.uniform(60, 900, len(dup))), unit="s")
    ev["es_reintento"] = False
    dup["es_reintento"] = True
    ev = pd.concat([ev, dup], ignore_index=True)
    ev["ts_recibido"] = ev["ts_recibido"].dt.floor("ms")
    ev = ev.sort_values(["ts_recibido", "evento_id"]).reset_index(drop=True)
    columnas = ["evento_id", "pedido_id", "zona", "tipo", "ts_evento", "ts_recibido",
                "espera_asignacion_s", "app", "es_reintento"]
    ev[columnas].to_parquet(directorio / "eventos.parquet", index=False)

    inc = pd.DataFrame([{
        "incidente": f"I{n:02d}",
        "zona": z,
        "inicio": INICIO_SEMANA + timedelta(days=d, hours=int(ini[:2]), minutes=int(ini[3:])),
        "minutos": dur,
        "causa": causa,
    } for n, (d, z, ini, dur, causa, _, _) in enumerate(INCIDENTES, 1)])
    inc["fin"] = inc["inicio"] + pd.to_timedelta(inc["minutos"], unit="min")
    inc.to_parquet(directorio / "incidentes.parquet", index=False)
    return directorio / "eventos.parquet"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DIR_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    ruta = generar(a.dir, a.escala, a.seed)
    print(f"Eventos en {ruta}")
