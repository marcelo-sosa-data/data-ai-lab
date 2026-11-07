"""
Genera la base de Ayni, una billetera digital ficticia con tarjeta prepago Visa
que opera en Lima y provincias.

Qué trae la base:
  - registros por canal de adquisición desde enero de 2025; no todos activan
  - transacciones (compras con tarjeta, recargas de celular, pago de servicios
    y transferencias) hasta el 31 de octubre de 2026
  - gasto mensual de marketing por canal, con los bonos de bienvenida incluidos

Patrones que el análisis tiene que encontrar:
  - TikTok e influencers traen cuentas baratas que se van rápido y gastan poco
  - Google y referidos cuestan más pero se quedan y compran con tarjeta
  - dos campañas de "S/ 20 de bono" (nov 2025 y abr 2026) en TikTok e
    influencers, que atraen a cazadores de bono: usan el bono y se van
  - en 2026 marketing pasa presupuesto a TikTok porque su CAC es el más bajo
  - desde marzo de 2026 existe pago de servicios y la gente se va un poco menos
  - más uso en julio (gratificación), diciembre y en quincena y fin de mes

La tabla aux_clientes guarda los parámetros verdaderos de cada cliente; el
análisis no la lee.

Uso:
    python datos/generar_datos.py                  # base completa (~15 s)
    python datos/generar_datos.py --escala 0.1     # base chica para pruebas
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

RUTA_DEFECTO = Path(__file__).parent / "ayni.duckdb"
INICIO = date(2025, 1, 1)
FIN_REGISTROS = date(2026, 9, 30)
FIN_OBSERVACION = date(2026, 10, 31)
LANZAMIENTO_SERVICIOS = date(2026, 3, 1)
CAMPANIAS_BONO = {"2025-11", "2026-04"}

# canal: registros/mes al inicio, tasa de activación, días activos por día (media),
# forma gamma de esa tasa, churn mensual medio, ticket relativo, CAC objetivo (S/),
# % provincia, mezcla de tipos (compra, recarga, transferencia)
CANALES = {
    "Orgánico":       dict(reg=540, act=0.70, lam=0.20, forma=1.6, churn=0.085, ticket=1.00, cac=0.0, prov=0.30, mix=(0.50, 0.25, 0.25)),
    "Referidos":      dict(reg=370, act=0.78, lam=0.22, forma=1.8, churn=0.070, ticket=1.05, cac=21.0, prov=0.35, mix=(0.52, 0.20, 0.28)),
    "Meta Ads":       dict(reg=900, act=0.55, lam=0.15, forma=1.3, churn=0.140, ticket=0.95, cac=34.0, prov=0.30, mix=(0.45, 0.30, 0.25)),
    "TikTok Ads":     dict(reg=1150, act=0.40, lam=0.11, forma=1.1, churn=0.230, ticket=0.70, cac=16.0, prov=0.25, mix=(0.30, 0.50, 0.20)),
    "Google Search":  dict(reg=320, act=0.66, lam=0.21, forma=1.7, churn=0.090, ticket=1.55, cac=48.0, prov=0.25, mix=(0.68, 0.12, 0.20)),
    "Influencers":    dict(reg=540, act=0.45, lam=0.11, forma=1.0, churn=0.260, ticket=0.80, cac=24.0, prov=0.30, mix=(0.35, 0.45, 0.20)),
    "Agentes en tienda": dict(reg=390, act=0.82, lam=0.16, forma=1.5, churn=0.110, ticket=0.85, cac=27.0, prov=0.62, mix=(0.40, 0.40, 0.20)),
}

# multiplicador de uso por mes calendario (1 = enero)
ESTACIONALIDAD = {1: 0.93, 2: 0.91, 3: 0.97, 4: 0.97, 5: 1.00, 6: 1.00,
                  7: 1.13, 8: 0.99, 9: 0.98, 10: 1.00, 11: 1.04, 12: 1.22}

# ingreso neto: % de intercambio en compras, % de comisión en recargas,
# monto fijo por pago de servicio; las transferencias no dejan ingreso
COMISION_COMPRA = 0.0105
COMISION_RECARGA = 0.032
COMISION_SERVICIO = 0.80

DESCRIPCION_CANALES = {
    "Orgánico": "Descarga directa sin campaña atribuida",
    "Referidos": "Invitación de un cliente; S/ 10 de bono a cada uno al activar",
    "Meta Ads": "Anuncios en Facebook e Instagram",
    "TikTok Ads": "Anuncios en TikTok",
    "Google Search": "Búsqueda pagada (tarjeta prepago, billetera, cuenta sin banco)",
    "Influencers": "Creadores de contenido con código de descuento",
    "Agentes en tienda": "Activación asistida en bodegas y agentes aliados",
}


def _dias(d: date) -> int:
    return (d - INICIO).days


def _meses(desde: date, hasta: date) -> list[pd.Timestamp]:
    return list(pd.date_range(desde, hasta, freq="MS"))


def _peso_presupuesto(canal: str, mes: pd.Timestamp) -> float:
    """Volumen de registros relativo al inicio: crecimiento y el giro a TikTok en 2026."""
    k = (mes.year - 2025) * 12 + mes.month - 1
    peso = 1.025 ** k
    if mes.year == 2026:
        if canal == "TikTok Ads":
            peso *= 1.0 + 0.12 * min(mes.month, 6)  # hasta +72% en junio
        elif canal in ("Meta Ads", "Google Search"):
            peso *= 0.80
    if mes.strftime("%Y-%m") in CAMPANIAS_BONO and canal in ("TikTok Ads", "Influencers"):
        peso *= 2.1
    if mes.month == 12:
        peso *= 1.10
    return peso


def generar(ruta: str | Path = RUTA_DEFECTO, escala: float = 1.0, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fin_obs = _dias(FIN_OBSERVACION)
    lanz = _dias(LANZAMIENTO_SERVICIOS)

    # ------------------------------------------------------------- registros
    bloques = []
    for mes in _meses(INICIO, FIN_REGISTROS):
        dias_mes = mes.days_in_month
        for canal, p in CANALES.items():
            n = rng.poisson(p["reg"] * escala * _peso_presupuesto(canal, mes))
            if n == 0:
                continue
            bloques.append(pd.DataFrame({
                "canal": canal,
                "dia_registro": _dias(mes.date()) + rng.integers(0, dias_mes, n),
                "campania_bono": mes.strftime("%Y-%m") in CAMPANIAS_BONO
                and canal in ("TikTok Ads", "Influencers"),
            }))
    reg = pd.concat(bloques, ignore_index=True)
    reg = reg.sort_values("dia_registro", kind="stable").reset_index(drop=True)
    n = len(reg)
    par = pd.DataFrame([CANALES[c] for c in reg.canal])

    reg["region"] = np.where(rng.random(n) < par.prov.to_numpy(), "Provincia", "Lima")
    reg["edad"] = rng.choice(["18-24", "25-34", "35-44", "45+"], n, p=[0.34, 0.38, 0.18, 0.10])
    tasa_act = par.act.to_numpy() * np.where(reg.campania_bono, 1.25, 1.0)
    activa = rng.random(n) < np.clip(tasa_act, 0, 0.95)
    reg["dia_activacion"] = np.where(
        activa, reg.dia_registro + np.floor(rng.exponential(2.5, n)).astype(int), -1)
    activa &= reg.dia_activacion.to_numpy() <= fin_obs
    reg.loc[~activa, "dia_activacion"] = -1

    # cazadores de bono: activan por los S/ 20, los gastan y no vuelven
    cazador = activa & reg.campania_bono.to_numpy() & (rng.random(n) < 0.45)

    # -------------------------------------------- parámetros de cada cliente
    # un "compromiso" latente comparte un poco de señal entre frecuencia y permanencia
    z = rng.normal(size=n)
    forma = par.forma.to_numpy()
    lam = rng.gamma(forma, par.lam.to_numpy() / forma) * np.exp(0.25 * z - 0.03)
    churn_medio = par.churn.to_numpy()
    conc = 4.0
    churn = rng.beta(churn_medio * conc, (1 - churn_medio) * conc)
    churn = np.clip(churn * np.exp(-0.30 * z), 0.003, 0.95)
    ticket = par.ticket.to_numpy() * rng.lognormal(0, 0.45, n)
    adopta_servicios = rng.random(n) < 0.45

    # ------------------------------------------------------- vida del cliente
    # churn mensual con un primer mes más duro; desde marzo 2026 se van un poco menos
    t0 = reg.dia_activacion.to_numpy()
    muerte = np.full(n, fin_obs + 1, dtype=np.int64)
    vivo = activa & ~cazador
    for k in range(24):
        inicio_mes = t0 + int(round(30.4 * k))
        h = churn * (1.7 if k == 0 else 1.0)
        h = np.where(inicio_mes >= lanz, h * np.where(adopta_servicios, 0.70, 0.95), h)
        cae = vivo & (inicio_mes <= fin_obs) & (rng.random(n) < np.clip(h, 0, 0.99))
        muerte[cae] = inicio_mes[cae] + rng.integers(0, 30, cae.sum())
        vivo &= ~cae
    muerte[cazador] = t0[cazador] + rng.integers(1, 12, cazador.sum())
    fin = np.minimum(muerte, fin_obs)

    # --------------------------------------------- días con transacciones
    # proceso de Poisson por cliente, con estacionalidad mensual y de quincena
    tope = 1.22 * 1.35
    lam_ev = np.where(cazador, 0.25, lam)
    duracion = np.where(activa, np.maximum(fin - t0, 0), 0)
    n_cand = rng.poisson(lam_ev * tope * duracion)
    idx = np.repeat(np.arange(n), n_cand)
    dia = t0[idx] + np.floor(rng.random(idx.size) * duracion[idx]).astype(np.int64) + 1
    fechas = pd.to_datetime(INICIO) + pd.to_timedelta(dia, unit="D")
    mult = fechas.month.map(ESTACIONALIDAD).to_numpy()
    dom = fechas.day.to_numpy()
    mult = mult * np.where(np.isin(dom, [15, 16]) | fechas.is_month_end | (dom == 1), 1.35, 1.0)
    acepta = rng.random(idx.size) < mult / tope
    idx, dia = idx[acepta], dia[acepta]
    # el día de activación siempre tiene la primera transacción
    act_idx = np.flatnonzero(activa)
    idx = np.concatenate([act_idx, idx])
    dia = np.concatenate([t0[act_idx], dia])
    dias_act = pd.DataFrame({"i": idx, "dia": dia}).drop_duplicates().sort_values(["i", "dia"])

    # ------------------------------------------------------- transacciones
    i = dias_act.i.to_numpy()
    d = dias_act.dia.to_numpy()
    n_tx = 1 + rng.poisson(0.35, i.size)
    i = np.repeat(i, n_tx)
    d = np.repeat(d, n_tx)
    m = i.size
    mix = np.array([CANALES[c]["mix"] for c in CANALES])
    cod_canal = pd.Categorical(reg.canal, categories=list(CANALES)).codes
    prob = mix[cod_canal[i]]
    u = rng.random(m)
    tipo = np.select([u < prob[:, 0], u < prob[:, 0] + prob[:, 1]],
                     ["Compra con tarjeta", "Recarga de celular"], "Transferencia")
    # pago de servicios desde el lanzamiento, solo para quien lo adopta
    usa_serv = adopta_servicios[i] & (d >= lanz) & (rng.random(m) < 0.30)
    tipo = np.where(usa_serv, "Pago de servicios", tipo)
    tipo = np.where(cazador[i] & (rng.random(m) < 0.7), "Recarga de celular", tipo)

    base_monto = np.select(
        [tipo == "Compra con tarjeta", tipo == "Recarga de celular", tipo == "Pago de servicios"],
        [rng.lognormal(np.log(42), 0.75, m), rng.choice([5, 10, 15, 20, 30], m, p=[.2, .35, .15, .2, .1]),
         rng.lognormal(np.log(75), 0.5, m)],
        rng.lognormal(np.log(60), 0.9, m))
    monto = np.where(tipo == "Recarga de celular", base_monto, base_monto * ticket[i])
    monto = np.round(np.clip(monto, 1, 4000), 2)
    ingreso = np.select(
        [tipo == "Compra con tarjeta", tipo == "Recarga de celular", tipo == "Pago de servicios"],
        [monto * COMISION_COMPRA, monto * COMISION_RECARGA, np.full(m, COMISION_SERVICIO)], 0.0)
    # hora del día: mañana, almuerzo y noche
    hora = np.clip(np.round(rng.choice([8.5, 13, 20], m, p=[.25, .35, .40]) + rng.normal(0, 2, m)), 0, 23)
    fecha_hora = (pd.to_datetime(INICIO) + pd.to_timedelta(d, unit="D")
                  + pd.to_timedelta(hora * 60 + rng.integers(0, 60, m), unit="min"))

    tx = pd.DataFrame({
        "id_cliente": i + 1, "fecha_hora": fecha_hora, "tipo": tipo,
        "monto": monto, "ingreso_neto": np.round(ingreso, 4),
    }).sort_values(["fecha_hora", "id_cliente"], kind="stable").reset_index(drop=True)
    tx.insert(0, "id_transaccion", np.arange(1, len(tx) + 1))

    # ------------------------------------------------------- tablas finales
    origen = pd.to_datetime(INICIO)
    clientes = pd.DataFrame({
        "id_cliente": np.arange(1, n + 1),
        "fecha_registro": pd.Series(origen + pd.to_timedelta(reg.dia_registro, unit="D")).dt.date,
        "fecha_activacion": pd.Series(
            origen + pd.to_timedelta(np.where(activa, t0, 0), unit="D")).dt.date.where(activa),
        "canal": reg.canal, "region": reg.region, "edad": reg.edad,
    })
    aux = pd.DataFrame({
        "id_cliente": clientes.id_cliente, "tasa_dias": np.round(lam_ev, 5),
        "churn_mensual": np.round(churn, 5), "ticket_relativo": np.round(ticket, 4),
        "cazador_bono": cazador, "adopta_servicios": adopta_servicios,
        "fecha_fin_real": pd.Series(origen + pd.to_timedelta(np.where(activa, muerte, 0), unit="D"))
        .dt.date.where(activa & (muerte <= fin_obs)),
    })

    # gasto de marketing: CAC objetivo por activación, con ruido y los bonos de campaña
    act = clientes.dropna(subset=["fecha_activacion"]).copy()
    act["mes"] = pd.to_datetime(act.fecha_activacion).dt.to_period("M").dt.to_timestamp()
    act = act[act.mes <= pd.Timestamp(FIN_REGISTROS)]
    activ = act.groupby(["mes", "canal"]).size().rename("activaciones").reset_index()
    activ["cac_obj"] = activ.canal.map(lambda c: CANALES[c]["cac"])
    bono = activ.mes.dt.strftime("%Y-%m").isin(CAMPANIAS_BONO) & activ.canal.isin(["TikTok Ads", "Influencers"])
    ruido = rng.lognormal(0, 0.07, len(activ))
    activ["gasto_medios"] = np.round(activ.activaciones * activ.cac_obj * ruido
                                     * np.where(activ.canal == "Referidos", 0.05, 1.0), 2)
    activ["gasto_bonos"] = np.round(activ.activaciones * np.select(
        [activ.canal == "Referidos", bono], [20.0, 20.0], 0.0), 2)
    gasto = activ[activ.canal != "Orgánico"][["mes", "canal", "gasto_medios", "gasto_bonos"]]
    gasto["mes"] = gasto.mes.dt.date

    canales = pd.DataFrame({"canal": list(CANALES), "descripcion": [DESCRIPCION_CANALES[c] for c in CANALES]})

    if ruta.exists():
        ruta.unlink()
    con = duckdb.connect(str(ruta))
    for nombre, df in [("canales", canales), ("clientes", clientes), ("transacciones", tx),
                       ("gasto_marketing", gasto), ("aux_clientes", aux)]:
        con.register("df", df)
        con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM df")
        con.unregister("df")
    con.execute("ALTER TABLE transacciones ALTER fecha_hora TYPE TIMESTAMP")
    comentarios = {
        "clientes": "Una fila por cuenta registrada; fecha_activacion es el día de la primera transacción",
        "transacciones": "Movimientos de la billetera; ingreso_neto ya descuenta el costo del procesador",
        "gasto_marketing": "Gasto mensual por canal; gasto_bonos son los bonos de bienvenida pagados",
        "aux_clientes": "Parámetros verdaderos del simulador; el análisis no la usa",
    }
    for t, c in comentarios.items():
        con.execute(f"COMMENT ON TABLE {t} IS '{c}'")
    con.close()
    return ruta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ruta", default=RUTA_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    ruta = generar(a.ruta, a.escala, a.seed)
    con = duckdb.connect(str(ruta), read_only=True)
    for t in ("clientes", "transacciones", "gasto_marketing"):
        print(f"{t:<16} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>10,}")


if __name__ == "__main__":
    main()
