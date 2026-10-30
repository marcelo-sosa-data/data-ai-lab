"""
Genera los datos de "Chasqui", una app de delivery ficticia que opera en Lima,
Arequipa, Trujillo y Piura, con los cinco experimentos A/B que corrió en 2026.

Se simula por usuario y por día: si abre la app (sesión) y, si abre, si pide.
Cada experimento asigna a los usuarios con el mismo hash que usa el análisis y
registra la primera exposición; el efecto empieza ese día y dura hasta el fin de
la ventana. Los efectos verdaderos se guardan en `efectos_reales`, que el análisis
no lee: solo sirve para comprobar que lo recupera.

Patrones que trae la base:
  - usuarios con frecuencias muy distintas (pocos piden mucho) y persistentes en el
    tiempo: eso es lo que aprovecha CUPED
  - viernes a domingo y quincena piden más; julio (frío y Fiestas Patrias) es el mes alto
  - Lima pide más seguido y con ticket más alto que provincia
  - usuarios nuevos llegan durante todo el año, con un primer mes más activo
  - EXP-01: efecto chico en pedidos (+2%), difícil de ver sin reducir varianza
  - EXP-02: el envío gratis hace que la gente "complete" el carrito hasta S/ 35
    y pida un poco más, pero la tarifa que se deja de cobrar pesa en el margen
  - EXP-03: efecto novedad: el recomendado funciona la primera semana y se apaga
  - EXP-04: más pedidos, pero muchas más cancelaciones (el ETA no se cumple)
  - EXP-05: sin efecto real, pero con un bug de logging en Android antiguo que
    registra la exposición recién en la segunda sesión del grupo tratamiento

Uso:
    python datos/generar_datos.py                  # base completa (~40 s)
    python datos/generar_datos.py --escala 0.2     # menos usuarios, para pruebas
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from experimentos.asignacion import asignar  # noqa: E402
from experimentos.catalogo import EXPERIMENTOS, PERIODO_AA  # noqa: E402

RUTA_DEFECTO = Path(__file__).parent / "chasqui.duckdb"
FECHA_INICIO = date(2025, 12, 1)
FECHA_FIN = date(2026, 9, 27)
USUARIOS = 150_000
BLOQUE = 25_000

CIUDADES = {  # participación, frecuencia, ticket, tarifa de envío, costo del rider
    "Lima": (0.62, 1.10, 1.12, 5.9, 6.6),
    "Arequipa": (0.15, 0.92, 0.95, 4.9, 5.2),
    "Trujillo": (0.12, 0.86, 0.90, 4.9, 5.0),
    "Piura": (0.11, 0.80, 0.88, 4.9, 5.0),
}
COMISION = 0.18
DIA_SEMANA = np.array([0.84, 0.83, 0.90, 0.96, 1.18, 1.26, 1.08])  # lun..dom
MES = {12: 1.08, 1: 0.92, 2: 0.90, 3: 0.97, 4: 1.00, 5: 1.02, 6: 1.06, 7: 1.12, 8: 1.04, 9: 1.00}
FERIADOS = {"2025-12-24": 1.25, "2025-12-25": 0.80, "2025-12-31": 1.30, "2026-01-01": 1.15,
            "2026-04-02": 1.10, "2026-04-03": 1.15, "2026-05-01": 1.10, "2026-06-29": 1.10,
            "2026-07-28": 1.30, "2026-07-29": 1.25, "2026-08-30": 1.10}

# Efectos verdaderos (lo que el análisis tiene que recuperar)
EF01_PEDIDOS = 1.02
EF02_UMBRAL, EF02_PEDIDOS, EF02_COFINANCIA = 35.0, 1.03, 0.75
EF02_COMPLETA = {"Lima": 0.30, "provincia": 0.40}  # prob. de subir el carrito a S/ 35+
EF03_BASE, EF03_NOVEDAD, EF03_DIAS = 0.008, 0.090, 5.0
EF04_PEDIDOS, EF04_CANCELACION = 1.035, 1.55


def _fechas() -> pd.DatetimeIndex:
    return pd.date_range(FECHA_INICIO, FECHA_FIN, freq="D")


def _factor_dia(fechas: pd.DatetimeIndex, rng) -> np.ndarray:
    f = DIA_SEMANA[fechas.dayofweek] * fechas.month.map(MES).to_numpy()
    quincena = (fechas.day == 15) | (fechas.day == 16) | fechas.is_month_end | (fechas.day == 1)
    f = f * np.where(quincena, 1.12, 1.0)
    fer = pd.Series(FERIADOS)
    f = f * pd.Series(fechas.strftime("%Y-%m-%d")).map(fer).fillna(1.0).to_numpy()
    return f * np.exp(rng.normal(0, 0.05, len(fechas)))


def _usuarios(rng, n: int) -> pd.DataFrame:
    ciudades = list(CIUDADES)
    ciudad = rng.choice(ciudades, n, p=[CIUDADES[c][0] for c in ciudades])
    lima = ciudad == "Lima"
    ios = rng.random(n) < np.where(lima, 0.38, 0.20)
    android_antiguo = ~ios & (rng.random(n) < np.where(lima, 0.16, 0.30))
    # 70% ya estaba registrado al empezar la base; el resto llega durante el año
    antiguos = rng.random(n) < 0.70
    dias_total = (FECHA_FIN - FECHA_INICIO).days
    inicio = np.datetime64(FECHA_INICIO, "D")
    offset = np.where(antiguos, -rng.integers(1, 3 * 365, n), (dias_total * rng.random(n) ** 0.85).astype(int))
    registro = inicio + offset.astype("timedelta64[D]")
    frec = _por_ciudad(ciudad, 1)
    frecuencia = (rng.gamma(0.8, 0.055 / 0.8, n) * frec * np.where(ios, 1.15, 1.0)
                  * np.where(android_antiguo, 0.70, 1.0))
    ticket = (np.exp(rng.normal(np.log(36), 0.28, n)) * _por_ciudad(ciudad, 2)
              * np.where(android_antiguo, 0.90, 1.0))
    # baja: después de esta fecha el usuario casi no vuelve (media de 16 meses)
    baja = registro + (30 + rng.exponential(16 * 30, n)).astype(int).astype("timedelta64[D]")
    return pd.DataFrame({
        "id_usuario": np.arange(1, n + 1),
        "ciudad": ciudad,
        "plataforma": np.where(ios, "ios", "android"),
        "version_app": np.where(ios, "ios", np.where(android_antiguo, "android<6", "android>=6")),
        "fecha_registro": pd.to_datetime(registro),
        "_frecuencia": frecuencia,
        "_ticket": ticket,
        "_baja": pd.to_datetime(baja),
    })


def _por_ciudad(ciudad: np.ndarray, col: int) -> np.ndarray:
    return pd.Series(ciudad).map({c: v[col] for c, v in CIUDADES.items()}).to_numpy()


def _ventanas(fechas: pd.DatetimeIndex) -> dict[str, tuple[int, int]]:
    idx = {f: i for i, f in enumerate(fechas)}
    v = {e.id: (idx[pd.Timestamp(e.inicio)], idx[pd.Timestamp(e.fin)]) for e in EXPERIMENTOS}
    v["AA"] = (idx[pd.Timestamp(PERIODO_AA[0])], idx[pd.Timestamp(PERIODO_AA[1])])
    return v


def _primera(mask: np.ndarray, desde: int, hasta: int, n: int = 1) -> np.ndarray:
    """Índice del día de la n-ésima sesión en la ventana, -1 si no hubo."""
    sub = mask[:, desde:hasta + 1]
    acum = np.cumsum(sub, axis=1)
    hay = acum[:, -1] >= n
    pos = np.argmax(acum >= n, axis=1) + desde
    return np.where(hay, pos, -1)


def _bloque(rng, u: pd.DataFrame, fechas, f_dia, ventanas, asig) -> tuple[list, list]:
    n, d = len(u), len(fechas)
    dia_num = np.arange(d)
    inicio = (u.fecha_registro.to_numpy() - np.datetime64(FECHA_INICIO)).astype("timedelta64[D]").astype(int)
    baja = (u._baja.to_numpy() - np.datetime64(FECHA_INICIO)).astype("timedelta64[D]").astype(int)
    activo = dia_num[None, :] >= inicio[:, None]
    desde_reg = dia_num[None, :] - inicio[:, None]
    # primer mes más activo (cupón de bienvenida), y después de la baja casi nada
    vida = np.where(desde_reg < 30, 1.5, 1.0) * np.where(dia_num[None, :] > baja[:, None], 0.06, 1.0)
    # ruido por usuario y mes: la frecuencia se mueve, pero no tanto
    meses = fechas.year * 12 + fechas.month
    _, mes_idx = np.unique(meses, return_inverse=True)
    ruido_mes = np.exp(rng.normal(-0.06, 0.35, (n, mes_idx.max() + 1)))[:, mes_idx]
    lam = u._frecuencia.to_numpy()[:, None] * f_dia[None, :] * vida * ruido_mes * activo

    p_sesion = np.minimum(0.92, 2.5 * lam)
    sesion = rng.random((n, d)) < p_sesion
    q = np.divide(lam, p_sesion, out=np.zeros_like(lam), where=p_sesion > 0)

    lima = (u.ciudad == "Lima").to_numpy()
    antiguo = (u.version_app == "android<6").to_numpy()
    expos, exp_dia = [], {}
    for id_exp, (a, b) in ventanas.items():
        dia = _primera(sesion, a, b)
        tr = asig[id_exp] if id_exp != "AA" else np.zeros(n, bool)
        exp_dia[id_exp] = (dia, tr)
        registrado = dia.copy()
        if id_exp == "EXP-05":
            # bug: en Android antiguo, el tratamiento registra la exposición en la 2da sesión
            seg = _primera(sesion, a, b, n=2)
            registrado = np.where(tr & antiguo, seg, dia)
        ok = registrado >= 0
        expos.append(pd.DataFrame({
            "id_experimento": id_exp,
            "id_usuario": u.id_usuario.to_numpy()[ok],
            "variante": np.where(tr[ok], "tratamiento", "control"),
            "fecha_exposicion": fechas[registrado[ok]],
        }))

    def expuesto(id_exp):
        dia, tr = exp_dia[id_exp]
        _, b = ventanas[id_exp]
        m = tr[:, None] & (dia[:, None] >= 0) & (dia_num[None, :] >= dia[:, None]) & (dia_num[None, :] <= b)
        return m, dia

    m01, _ = expuesto("EXP-01")
    m02, _ = expuesto("EXP-02")
    m03, d03 = expuesto("EXP-03")
    m04, _ = expuesto("EXP-04")
    q = q * np.where(m01, EF01_PEDIDOS, 1.0) * np.where(m02, EF02_PEDIDOS, 1.0) * np.where(m04, EF04_PEDIDOS, 1.0)

    pide = sesion & (rng.random((n, d)) < np.minimum(q, 0.97))
    dobles = pide & (rng.random((n, d)) < 0.04)
    ui, di = np.nonzero(pide)
    ui = np.concatenate([ui, np.nonzero(dobles)[0]])
    di = np.concatenate([di, np.nonzero(dobles)[1]])
    k = len(ui)

    monto = u._ticket.to_numpy()[ui] * np.exp(rng.normal(-0.32 ** 2 / 2, 0.32, k))
    monto = np.maximum(8.0, monto)
    ciudad = u.ciudad.to_numpy()[ui]
    tarifa = _por_ciudad(ciudad, 3).astype(float)
    rider = _por_ciudad(ciudad, 4).astype(float) * np.exp(rng.normal(0, 0.08, k))
    comision = np.full(k, COMISION)

    # EXP-02: completar el carrito hasta el umbral y tarifa 0 desde S/ 35
    t02 = m02[ui, di]
    p_comp = np.where(lima[ui], EF02_COMPLETA["Lima"], EF02_COMPLETA["provincia"])
    completa = t02 & (monto >= 24) & (monto < EF02_UMBRAL) & (rng.random(k) < p_comp)
    monto = np.where(completa, rng.uniform(EF02_UMBRAL, EF02_UMBRAL + 6, k), monto)
    gratis = t02 & (monto >= EF02_UMBRAL)
    # el comercio cofinancia una parte del envío gratis con más comisión
    comision = np.where(gratis, COMISION + EF02_COFINANCIA * tarifa / np.maximum(monto, 1), comision)
    tarifa = np.where(gratis, 0.0, tarifa)

    # EXP-03: el complemento sube el ticket, sobre todo los primeros días
    t03 = m03[ui, di]
    dias_desde = di - d03[ui]
    uplift = EF03_BASE + EF03_NOVEDAD * np.exp(-np.maximum(dias_desde, 0) / EF03_DIAS)
    monto = np.where(t03, monto * (1 + uplift * rng.uniform(0.0, 2.0, k)), monto)
    monto = np.round(monto, 1)

    minutos = np.round(rng.gamma(9, np.where(lima[ui], 36, 31) / 9, k)).astype(int)
    p_cancel = 0.028 + 0.0015 * np.maximum(minutos - 40, 0)
    p_cancel = np.where(m04[ui, di], p_cancel * EF04_CANCELACION, p_cancel)
    cancelado = rng.random(k) < p_cancel

    hora = rng.choice(24, k, p=_HORAS)
    minuto = rng.integers(0, 60, k)
    creado = fechas[di] + pd.to_timedelta(hora * 60 + minuto, unit="m")
    margen = np.where(cancelado, 0.0, comision * monto + tarifa - rider)
    pedidos = pd.DataFrame({
        "id_usuario": u.id_usuario.to_numpy()[ui],
        "creado_en": creado,
        "monto": monto,
        "tarifa_envio": tarifa,
        "comision": np.round(comision * monto, 2),
        "costo_rider": np.round(rider, 2),
        "margen": np.round(margen, 2),
        "minutos_entrega": np.where(cancelado, -1, minutos),
        "cancelado": cancelado,
    })
    return [pedidos], expos


_HORAS = np.array([0.4, 0.2, 0.1, 0.1, 0.1, 0.2, 0.5, 1.2, 2.2, 2.4, 2.6, 4.8, 9.8, 10.4, 6.2, 3.2,
                   3.0, 3.6, 5.4, 9.6, 11.2, 9.2, 5.6, 2.0])
_HORAS = _HORAS / _HORAS.sum()


def generar(ruta: Path = RUTA_DEFECTO, escala: float = 1.0, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    ruta = Path(ruta)
    fechas = _fechas()
    f_dia = _factor_dia(fechas, rng)
    ventanas = _ventanas(fechas)
    usuarios = _usuarios(rng, int(USUARIOS * escala))
    asig = {e.id: asignar(usuarios.id_usuario.to_numpy(), e.sal, e.reparto) for e in EXPERIMENTOS}

    pedidos, expos = [], []
    for ini in range(0, len(usuarios), BLOQUE):
        sl = slice(ini, ini + BLOQUE)
        u = usuarios.iloc[sl].reset_index(drop=True)
        p, e = _bloque(rng, u, fechas, f_dia, ventanas, {k: v[sl] for k, v in asig.items()})
        pedidos += p
        expos += e
    pedidos = pd.concat(pedidos).sort_values("creado_en", kind="stable").reset_index(drop=True)
    pedidos.insert(0, "id_pedido", np.arange(1, len(pedidos) + 1))
    pedidos["minutos_entrega"] = pedidos.minutos_entrega.astype("Int64").where(pedidos.minutos_entrega >= 0)
    expos = pd.concat(expos, ignore_index=True)

    experimentos = pd.DataFrame([{
        "id_experimento": e.id, "nombre": e.nombre, "hipotesis": e.hipotesis,
        "fecha_inicio": pd.Timestamp(e.inicio), "fecha_fin": pd.Timestamp(e.fin),
        "metrica_primaria": e.primaria, "reparto_tratamiento": e.reparto, "sal": e.sal,
        "guardrails": json.dumps([{"metrica": g.metrica, "margen": g.margen} for g in e.guardrails]),
    } for e in EXPERIMENTOS])
    efectos = pd.DataFrame([
        ("EXP-01", "pedidos por sesión", f"x{EF01_PEDIDOS}"),
        ("EXP-02", "pedidos por sesión", f"x{EF02_PEDIDOS}"),
        ("EXP-02", "carrito de S/ 24-35 que sube al umbral", json.dumps(EF02_COMPLETA)),
        ("EXP-02", "cofinanciamiento del comercio", f"{EF02_COFINANCIA:.0%} de la tarifa"),
        ("EXP-03", "ticket", f"+{EF03_BASE:.1%} + {EF03_NOVEDAD:.1%}·exp(-días/{EF03_DIAS:g})"),
        ("EXP-04", "pedidos por sesión", f"x{EF04_PEDIDOS}"),
        ("EXP-04", "probabilidad de cancelar", f"x{EF04_CANCELACION}"),
        ("EXP-05", "ninguno", "bug de logging en android<6, grupo tratamiento"),
    ], columns=["id_experimento", "variable", "efecto"])

    cols_u = ["id_usuario", "ciudad", "plataforma", "version_app", "fecha_registro"]
    if ruta.exists():
        ruta.unlink()
    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in {"usuarios": usuarios[cols_u], "pedidos": pedidos, "exposiciones": expos,
                           "experimentos": experimentos, "efectos_reales": efectos}.items():
            con.register("_df", df)
            con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM _df")
            con.unregister("_df")
        con.execute("ALTER TABLE pedidos ADD COLUMN fecha DATE")
        con.execute("UPDATE pedidos SET fecha = CAST(creado_en AS DATE)")
        con.execute("UPDATE exposiciones SET fecha_exposicion = CAST(fecha_exposicion AS DATE)")
        con.execute("CREATE INDEX ix_pedidos_usuario ON pedidos (id_usuario)")
        for sql in COMENTARIOS:
            con.execute(sql)
    finally:
        con.close()
    return ruta


COMENTARIOS = [
    "COMMENT ON TABLE usuarios IS 'Usuarios registrados de la app'",
    "COMMENT ON TABLE pedidos IS 'Un pedido por fila; margen = comisión + tarifa de envío - costo del rider'",
    "COMMENT ON TABLE exposiciones IS 'Primera exposición registrada de cada usuario a cada experimento'",
    "COMMENT ON TABLE experimentos IS 'Registro de experimentos: hipótesis, ventana, métrica primaria y guardrails'",
    "COMMENT ON TABLE efectos_reales IS 'Efectos verdaderos del generador; el análisis no la lee'",
    "COMMENT ON COLUMN pedidos.margen IS 'S/ por pedido; 0 si se canceló'",
]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ruta", type=Path, default=RUTA_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    print(generar(a.ruta, a.escala, a.seed))
