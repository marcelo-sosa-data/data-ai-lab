"""
Genera los datos de "Tinkuy Pay", una pasarela de pagos ficticia para comercios
peruanos (bodegas, restaurantes, farmacias, tiendas de ropa y servicios) que cobran
con QR interoperable, tarjeta o link de pago desde la app o un POS.

Se simula por comercio y por día: cuántos cobros intenta (Poisson) y, para cada
cobro, hora, método, emisor, monto y si se aprueba.

Patrones que trae la base:
  - fin de semana fuerte en restaurantes y ropa; servicios casi no cobra el domingo
  - días de pago (1, 15, 16 y fin de mes) con más cobros; del 10 al 14 y del 25 al 29
    se rechazan algo más débitos y QR por fondos insuficientes
  - julio y diciembre altos (gratificación), campaña navideña fuerte en ropa; la
    estacionalidad mensual cambia de forma gradual, sin saltos el día 1
  - el QR pasa de ~36% a ~62% de los cobros: cobra menos comisión que la tarjeta
  - campaña "Bodega Digital" (may-jul 2026): llegan muchas bodegas, de ticket bajo
  - precios que suben ~3% al año dentro de cada rubro
  - incidentes con fecha conocida (tabla `incidentes`, que el monitor no lee):
      * 21 mar 2026, 18:00-21:59: caída del proveedor de red de los POS
      * 20 may 2026: no se cargaron las transacciones de Arequipa (falla de ETL)
      * 14 ago 2026, 11:00-15:59: Banco del Pacífico no responde como emisor
      * 3 al 12 set 2026: la versión 5.12 de Android falla en cobros QR; 5.12.1 lo corrige
  - unos pocos comercios de prueba que se borraron del maestro pero dejaron cobros

Uso:
    python datos/generar_datos.py                  # base completa (~2.5 millones de cobros)
    python datos/generar_datos.py --escala 0.2     # más chica, para pruebas
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from kpis.calendario import es_campania_navidad, es_dia_de_pago, es_feriado  # noqa: E402

RUTA_DEFECTO = Path(__file__).parent / "tinkuy.duckdb"
INICIO, FIN = pd.Timestamp("2025-07-01"), pd.Timestamp("2026-09-30")

RUBROS = ["bodega", "restaurante", "farmacia", "ropa", "servicios"]
P_RUBRO = [0.33, 0.26, 0.11, 0.12, 0.18]
P_PYME = {"bodega": 0.08, "restaurante": 0.30, "farmacia": 0.35, "ropa": 0.30, "servicios": 0.40}
COBROS_DIA = {"bodega": 1.6, "restaurante": 2.2, "farmacia": 1.5, "ropa": 0.8, "servicios": 0.6}
TICKET = {"bodega": 14.0, "restaurante": 36.0, "farmacia": 31.0, "ropa": 92.0, "servicios": 118.0}
REGIONES = ["Lima", "Arequipa", "Trujillo", "Piura", "Cusco"]
P_REGION = [0.58, 0.12, 0.10, 0.08, 0.12]

DIA_SEMANA = {  # lun..dom
    "bodega": [0.95, 0.93, 0.95, 0.98, 1.05, 1.12, 1.02],
    "restaurante": [0.80, 0.82, 0.88, 0.95, 1.22, 1.35, 1.18],
    "farmacia": [1.02, 1.00, 1.00, 1.00, 1.02, 1.00, 0.96],
    "ropa": [0.80, 0.78, 0.82, 0.90, 1.10, 1.45, 1.15],
    "servicios": [1.15, 1.15, 1.12, 1.12, 1.10, 0.80, 0.46],
}
MES = {1: 0.96, 2: 0.94, 3: 0.98, 4: 0.99, 5: 1.00, 6: 1.00, 7: 1.07, 8: 1.00, 9: 0.99,
       10: 1.00, 11: 1.01, 12: 1.10}
FERIADO = {"bodega": 1.0, "restaurante": 1.20, "farmacia": 1.0, "ropa": 1.10, "servicios": 0.45}
NAVIDAD = {"bodega": 1.15, "restaurante": 1.10, "farmacia": 1.0, "ropa": 1.9, "servicios": 1.0}

METODOS = ["qr", "debito", "credito", "link"]
APROBACION = {"qr": 0.965, "debito": 0.935, "credito": 0.915, "link": 0.885}
COMISION = {"qr": 0.0099, "debito": 0.0249, "credito": 0.0349, "link": 0.0399}
EMISORES = ["Banco Andino", "Banco del Pacífico", "Banco Inca", "Caja Sur", "Billetera Q"]
P_EMISOR = np.array([0.33, 0.27, 0.19, 0.09, 0.12])
AJUSTE_EMISOR = {"Caja Sur": -0.025, "Billetera Q": 0.005}
MOTIVOS = ["fondos_insuficientes", "fraude", "emisor_no_disponible", "error_tecnico"]
P_MOTIVO = [0.55, 0.12, 0.13, 0.20]

# versiones de la app: cada comercio actualiza con su propio rezago
VERSIONES = [("5.9", "2024-01-01"), ("5.10", "2025-11-12"), ("5.11", "2026-07-15"),
             ("5.12", "2026-09-03"), ("5.12.1", "2026-09-10")]

INCIDENTES = pd.DataFrame([
    {"id_incidente": "INC-1", "inicio": "2026-03-21 18:00", "fin": "2026-03-21 21:59", "dimension": "plataforma",
     "valor": "pos", "descripcion": "Caída del proveedor de red de los POS"},
    {"id_incidente": "INC-2", "inicio": "2026-05-20 00:00", "fin": "2026-05-20 23:59", "dimension": "region",
     "valor": "Arequipa", "descripcion": "Falla de ETL: no se cargaron las transacciones de Arequipa"},
    {"id_incidente": "INC-3", "inicio": "2026-08-14 11:00", "fin": "2026-08-14 15:59", "dimension": "emisor",
     "valor": "Banco del Pacífico", "descripcion": "El emisor no responde: rechazos por emisor no disponible"},
    {"id_incidente": "INC-4", "inicio": "2026-09-03 00:00", "fin": "2026-09-12 23:59", "dimension": "version_app",
     "valor": "5.12", "descripcion": "Bug en cobros QR de la app Android 5.12 (hotfix 5.12.1 el 10 set)"},
])


def _comercios(rng, escala: float) -> pd.DataFrame:
    partes = []

    def lote(n, desde, hasta, canal, rubro=None):
        n = int(round(n * escala))
        if n == 0:
            return
        dias = (pd.Timestamp(hasta) - pd.Timestamp(desde)).days + 1
        alta = pd.Timestamp(desde) + pd.to_timedelta(rng.integers(0, dias, n), unit="D")
        r = np.full(n, rubro) if rubro else rng.choice(RUBROS, n, p=P_RUBRO)
        partes.append(pd.DataFrame({"fecha_alta": alta, "rubro": r, "canal_alta": canal}))

    lote(2600, "2024-01-01", "2025-06-30", "comercial")
    for i, mes in enumerate(pd.date_range(INICIO, FIN, freq="MS")):
        lote(170 * (1 + 0.03 * i), mes, mes + pd.offsets.MonthEnd(0), "comercial")
    for mes in pd.date_range("2026-05-01", "2026-07-01", freq="MS"):
        lote(750, mes, mes + pd.offsets.MonthEnd(0), "bodega_digital", rubro="bodega")

    c = pd.concat(partes, ignore_index=True).sort_values("fecha_alta", kind="stable").reset_index(drop=True)
    n = len(c)
    c.insert(0, "id_comercio", np.arange(10_001, 10_001 + n))
    c["region"] = rng.choice(REGIONES, n, p=P_REGION)
    pyme = rng.random(n) < c.rubro.map(P_PYME).to_numpy()
    pyme &= c.canal_alta.to_numpy() != "bodega_digital"
    c["segmento"] = np.where(pyme, "pyme", "micro")
    u = rng.random(n)
    c["plataforma"] = np.where(pyme, np.select([u < 0.60, u < 0.88], ["pos", "android"], "ios"),
                               np.select([u < 0.68, u < 0.85], ["android", "ios"], "pos"))
    # churn de ~2.5% mensual
    c["fecha_baja"] = c.fecha_alta + pd.to_timedelta(rng.exponential(40 * 30.4, n).astype(int), unit="D")
    c.loc[c.fecha_baja > FIN, "fecha_baja"] = pd.NaT
    sigma = 0.7
    c["_cobros"] = (c.rubro.map(COBROS_DIA) * np.where(pyme, 1.8, 0.7)
                    * rng.lognormal(-sigma**2 / 2, sigma, n))
    c["_ticket"] = rng.lognormal(0, 0.3, n)
    c["_rezago"] = rng.lognormal(np.log(5), 1.0, n)
    return c


def _grilla(c: pd.DataFrame) -> pd.DataFrame:
    """Una fila por comercio y día en que está afiliado."""
    desde = c.fecha_alta.clip(lower=INICIO)
    hasta = c.fecha_baja.fillna(FIN).clip(upper=FIN)
    dias = ((hasta - desde).dt.days + 1).clip(lower=0).to_numpy()
    idx = np.repeat(np.arange(len(c)), dias)
    offset = np.arange(dias.sum()) - np.repeat(np.cumsum(dias) - dias, dias)
    fecha = desde.to_numpy()[idx] + offset.astype("timedelta64[D]")
    return pd.DataFrame({"i": idx, "fecha": pd.DatetimeIndex(fecha)})


def _factor_mes(f: pd.DatetimeIndex) -> np.ndarray:
    """Estacionalidad mensual sin escalones: se interpola entre los días 15 de cada mes."""
    anclas = pd.date_range(INICIO - pd.offsets.MonthBegin(1), FIN + pd.offsets.MonthBegin(1), freq="MS")
    anclas = anclas + pd.Timedelta(days=14)
    x = (anclas - INICIO).days.to_numpy()
    return np.interp((f - INICIO).days.to_numpy(), x, anclas.month.map(MES).to_numpy())


def _perfil_horario(rubro: str) -> np.ndarray:
    h = np.arange(24)
    picos = {"bodega": [(9, 1.5, 1.0), (19.5, 1.8, 1.2)], "restaurante": [(13.3, 1.2, 1.4), (20.5, 1.4, 1.0)],
             "farmacia": [(11, 3, 1.0), (19, 2.5, 1.0)], "ropa": [(13, 2, 0.7), (18.5, 2, 1.2)],
             "servicios": [(11, 2.2, 1.0), (16, 2.2, 0.9)]}[rubro]
    p = sum(a * np.exp(-0.5 * ((h - m) / s) ** 2) for m, s, a in picos)
    p = p + 0.01
    p[:6] *= 0.1
    return p / p.sum()


def _version(plataforma: np.ndarray, fecha: pd.DatetimeIndex, rezago: np.ndarray) -> np.ndarray:
    v = np.full(len(fecha), VERSIONES[0][0], dtype=object)
    for nombre, lanzamiento in VERSIONES[1:]:
        # el hotfix se fuerza: llega en un cuarto del tiempo habitual
        r = rezago / 4 if nombre == "5.12.1" else rezago
        listo = fecha >= pd.Timestamp(lanzamiento) + pd.to_timedelta(r, unit="D")
        v[listo] = nombre
    v[plataforma == "pos"] = "pos-3"
    return v


def generar(ruta: Path = RUTA_DEFECTO, escala: float = 1.0, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    c = _comercios(rng, escala)
    g = _grilla(c)
    f = pd.DatetimeIndex(g.fecha)
    rubro = c.rubro.to_numpy()[g.i]

    lam = c._cobros.to_numpy()[g.i] * _factor_mes(f)
    for r in RUBROS:
        m = rubro == r
        fr = f[m]
        lam[m] *= (np.array(DIA_SEMANA[r])[fr.dayofweek]
                   * np.where(es_dia_de_pago(fr), 1.25 if r == "ropa" else 1.14, 1.0)
                   * np.where(es_feriado(fr), FERIADO[r], 1.0)
                   * np.where(es_campania_navidad(fr), NAVIDAD[r], 1.0))
    anios = ((f - INICIO).days / 365.25).to_numpy()
    edad = (f - c.fecha_alta.to_numpy()[g.i]).days.to_numpy()
    lam *= np.exp(0.10 * anios) * np.where(edad < 45, 0.45 + 0.55 * edad / 45, 1.0)

    n = rng.poisson(lam)
    fila = np.repeat(np.arange(len(g)), n)
    i = g.i.to_numpy()[fila]
    fecha = f[fila]
    rubro_t = rubro[fila]
    pyme = (c.segmento.to_numpy() == "pyme")[i]
    plataforma = c.plataforma.to_numpy()[i]
    N = len(fila)

    hora = np.empty(N, dtype=int)
    for r in RUBROS:
        m = rubro_t == r
        hora[m] = rng.choice(24, m.sum(), p=_perfil_horario(r))
    fecha_hora = fecha + pd.to_timedelta(hora * 3600 + rng.integers(0, 3600, N), unit="s")

    t = ((fecha - INICIO).days / 365.25).to_numpy()
    p_qr = 0.36 + 0.26 / (1 + np.exp(-((fecha - pd.Timestamp("2026-01-15")).days.to_numpy() / 70)))
    p_qr = np.where(pyme, p_qr * 0.7, p_qr)
    u = rng.random(N)
    p_link = np.where(rubro_t == "servicios", 0.30, 0.12)
    resto = (u - p_qr) / (1 - p_qr)
    metodo = np.where(u < p_qr, "qr", np.where(resto < p_link, "link",
                      np.where(resto < p_link + (1 - p_link) * 0.59, "debito", "credito")))

    emisor = np.where(metodo == "qr", rng.choice(EMISORES, N, p=P_EMISOR),
                      rng.choice(EMISORES[:4], N, p=P_EMISOR[:4] / P_EMISOR[:4].sum()))

    mediana = pd.Series(rubro_t).map(TICKET).to_numpy() * c._ticket.to_numpy()[i] * (1 + 0.03 * t)
    mediana = np.where(metodo == "qr", mediana * 0.8, mediana)
    monto = np.maximum(np.round(rng.lognormal(np.log(mediana), 0.55), 1), 1.0)

    version = _version(plataforma, fecha, c._rezago.to_numpy()[i])

    p = pd.Series(metodo).map(APROBACION).to_numpy() + pd.Series(emisor).map(AJUSTE_EMISOR).fillna(0).to_numpy()
    fin_quincena = ((fecha.day >= 10) & (fecha.day <= 14)) | ((fecha.day >= 25) & (fecha.day <= 29))
    p = p - np.where(fin_quincena & np.isin(metodo, ["qr", "debito"]), 0.012, 0)
    motivo_forzado = np.full(N, None, dtype=object)

    inc1 = (fecha_hora >= "2026-03-21 18:00") & (fecha_hora < "2026-03-21 22:00") & (plataforma == "pos")
    p[inc1] = 0.55
    motivo_forzado[inc1] = "error_tecnico"
    inc3 = ((fecha_hora >= "2026-08-14 11:00") & (fecha_hora < "2026-08-14 16:00")
            & (emisor == "Banco del Pacífico"))
    p[inc3] = 0.40
    motivo_forzado[inc3] = "emisor_no_disponible"
    inc4 = (version == "5.12") & (plataforma == "android") & (metodo == "qr")
    p[inc4] -= 0.14
    motivo_forzado[inc4] = "error_tecnico"

    aprobada = rng.random(N) < p
    motivo = np.where(aprobada, None, rng.choice(MOTIVOS, N, p=P_MOTIVO))
    forzar = ~aprobada & (motivo_forzado != None) & (rng.random(N) < 0.9)  # noqa: E711
    motivo[forzar] = motivo_forzado[forzar]

    tasa = pd.Series(metodo).map(COMISION).to_numpy() - np.where(pyme & (metodo != "qr"), 0.003, 0)
    comision = np.where(aprobada, np.round(monto * tasa, 2), 0.0)

    tx = pd.DataFrame({
        "fecha_hora": fecha_hora, "fecha": fecha.normalize(), "id_comercio": c.id_comercio.to_numpy()[i],
        "metodo": metodo, "emisor": emisor, "plataforma": plataforma, "version_app": version,
        "monto": monto, "estado": np.where(aprobada, "aprobada", "rechazada"), "motivo_rechazo": motivo,
        "comision": comision,
    })
    # INC-2: el 20 de mayo no se cargó Arequipa
    region_t = c.region.to_numpy()[i]
    tx = tx[~((tx.fecha == "2026-05-20") & (region_t == "Arequipa"))]
    tx = tx.sort_values("fecha_hora", kind="stable").reset_index(drop=True)
    tx.insert(0, "id_transaccion", np.arange(1, len(tx) + 1))

    # comercios de prueba borrados del maestro: sus cobros quedan huérfanos
    prueba = rng.choice(c.id_comercio.to_numpy(), max(1, int(len(c) * 0.003)), replace=False)
    maestro = c[~c.id_comercio.isin(prueba)].drop(columns=["_cobros", "_ticket", "_rezago", "plataforma"])

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.unlink(missing_ok=True)
    con = duckdb.connect(str(ruta))
    try:
        con.register("_c", maestro)
        con.execute("""CREATE TABLE comercios AS SELECT id_comercio, rubro, region, segmento, canal_alta,
                       CAST(fecha_alta AS DATE) AS fecha_alta, CAST(fecha_baja AS DATE) AS fecha_baja FROM _c""")
        con.register("_t", tx)
        con.execute("""CREATE TABLE transacciones AS SELECT id_transaccion, fecha_hora, CAST(fecha AS DATE) AS fecha,
                       id_comercio, metodo, emisor, plataforma, version_app,
                       CAST(monto AS DECIMAL(12, 2)) AS monto, estado, motivo_rechazo,
                       CAST(comision AS DECIMAL(12, 2)) AS comision FROM _t""")
        inc = INCIDENTES.assign(inicio=pd.to_datetime(INCIDENTES.inicio), fin=pd.to_datetime(INCIDENTES.fin))
        con.register("_i", inc)
        con.execute("CREATE TABLE incidentes AS SELECT * FROM _i")
        con.execute("COMMENT ON TABLE transacciones IS 'Un intento de cobro por fila, aprobado o rechazado'")
        con.execute("COMMENT ON TABLE comercios IS 'Maestro de comercios afiliados'")
        con.execute("COMMENT ON TABLE incidentes IS 'Incidentes reales del generador; el monitor no la lee'")
    finally:
        con.close()
    return ruta


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=RUTA_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    print(generar(a.salida, a.escala, a.seed))
