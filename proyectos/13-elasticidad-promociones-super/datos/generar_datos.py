"""
Genera la base sintética de Supermercados Qollqa: 15 locales en Lima y Callao,
40 productos de 8 categorías y 104 semanas de venta (nov 2024 – oct 2026).

La demanda semanal de cada producto en cada local sigue un modelo log-lineal:
elasticidad propia al precio (distinta por formato de tienda), sustitución entre
marcas de la misma categoría, efecto del encarte, caída posterior a la promoción
en los productos que se pueden almacenar, estacionalidad y gratificaciones.

El calendario de promociones imita la práctica del área comercial: una promoción
por categoría a la vez, más seguidas en temporada alta, con preferencia por las
marcas líderes y a veces con aporte del proveedor.

Las tablas aux_* guardan la verdad (parámetros y margen incremental real de cada
promoción con distintos descuentos). El análisis no las usa; solo la evaluación.

    python datos/generar_datos.py [--escala 0.3] [--seed 42]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

INICIO = pd.Timestamp("2024-11-04")  # lunes
N_SEMANAS = 104
VENTANA_POST = 2  # semanas después de la promoción en que se mide la caída
DESCUENTOS_GRILLA = (0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35)

# categoría: elasticidad media, sustitución, encarte, caída post, margen, precio base, unidades base
CATEGORIAS = {
    "Aceites":          dict(e=-1.9, cruz=0.8, enc=0.18, post=-1.1, margen=0.18, precio=9.9,  base=120),
    "Arroz":            dict(e=-0.9, cruz=0.5, enc=0.10, post=-0.7, margen=0.13, precio=22.9, base=90),
    "Detergentes":      dict(e=-2.2, cruz=0.9, enc=0.18, post=-1.3, margen=0.26, precio=26.9, base=60),
    "Papel higiénico":  dict(e=-1.8, cruz=0.8, enc=0.15, post=-1.3, margen=0.24, precio=24.9, base=70),
    "Gaseosas":         dict(e=-2.9, cruz=1.1, enc=0.30, post=-0.3, margen=0.24, precio=10.5, base=220),
    "Cervezas":         dict(e=-2.5, cruz=1.0, enc=0.32, post=-0.4, margen=0.22, precio=32.9, base=90),
    "Yogures":          dict(e=-1.5, cruz=1.2, enc=0.18, post=-0.1, margen=0.26, precio=7.9,  base=160),
    "Galletas":         dict(e=-2.6, cruz=0.6, enc=0.25, post=-0.2, margen=0.30, precio=4.5,  base=200),
}

MARCAS = {
    "Aceites": ["Dorado Premium 1 L", "Cocinera 1 L", "Valle Sur 1 L", "Girasol Andino 900 ml", "Qollqa 1 L"],
    "Arroz": ["Arrocera del Norte 5 kg", "Paisana Extra 5 kg", "Molino Real 5 kg", "Chiclayano 5 kg", "Qollqa 5 kg"],
    "Detergentes": ["Brillex 2.6 kg", "Espumil 2.6 kg", "Ola Azul 2.6 kg", "Limpio Max 2 kg", "Qollqa 2 kg"],
    "Papel higiénico": ["Suavex 24 rollos", "Nube Doble Hoja 20 rollos", "Algodón 24 rollos",
                        "Familiar 16 rollos", "Qollqa 24 rollos"],
    "Gaseosas": ["Kola Dorada 3 L", "Negra Cola 3 L", "Lima Limón 3 L", "Naranjita 3 L", "Qollqa Cola 3 L"],
    "Cervezas": ["Rímac Lager six pack", "Cumbre six pack", "Andina Rubia six pack", "Puerto six pack",
                 "Malta Negra six pack"],
    "Yogures": ["Lácteos del Sur 1 L", "Vaquita 1 L", "Pradera 1 L", "Mi Granja 1 L", "Qollqa 1 L"],
    "Galletas": ["Crocante x6", "Choco Rico x6", "Vainilla Sur x6", "Integral x6", "Qollqa x6"],
}
PARTICIPACION = np.array([0.34, 0.22, 0.16, 0.12, 0.16])
PRECIO_RELATIVO = np.array([1.10, 1.00, 0.96, 0.92, 0.80])

TIENDAS = [
    ("Hiper San Miguel", "San Miguel", "Hiper"), ("Hiper Surco", "Santiago de Surco", "Hiper"),
    ("Hiper Los Olivos", "Los Olivos", "Hiper"),
    ("Qollqa Miraflores", "Miraflores", "Super"), ("Qollqa Jesús María", "Jesús María", "Super"),
    ("Qollqa La Molina", "La Molina", "Super"), ("Qollqa San Borja", "San Borja", "Super"),
    ("Qollqa Callao", "Callao", "Super"), ("Qollqa Comas", "Comas", "Super"),
    ("Qollqa Ate", "Ate", "Super"),
    ("Express Barranco", "Barranco", "Express"), ("Express Lince", "Lince", "Express"),
    ("Express Pueblo Libre", "Pueblo Libre", "Express"), ("Express San Isidro", "San Isidro", "Express"),
    ("Express Magdalena", "Magdalena del Mar", "Express"),
]
VOLUMEN_FORMATO = {"Hiper": 2.3, "Super": 1.0, "Express": 0.35}
SENSIBILIDAD_FORMATO = {"Hiper": 1.15, "Super": 1.0, "Express": 0.75}


@dataclass
class Verdad:
    """Lo necesario para recalcular la demanda esperada sin ruido."""

    cat_de_sku: np.ndarray          # (P,) índice de categoría
    log_base: np.ndarray            # (T, P) log de unidades base por local Super
    log_tienda: np.ndarray          # (S,) volumen del local
    sens_tienda: np.ndarray         # (S,) multiplicador de la elasticidad
    elasticidad: np.ndarray         # (P,)
    cruz: np.ndarray                # (C,)
    enc: np.ndarray                 # (C,)
    post: np.ndarray                # (C,)
    precio_ref: np.ndarray          # (P,)
    peso_cruz: np.ndarray           # (P, P) peso de j en la sustitución de i

    def log_mu(self, precio: np.ndarray, encarte: np.ndarray, prof: np.ndarray) -> np.ndarray:
        """Log de la demanda esperada (S, T, P) dados precio, encarte y profundidad de descuento (T, P)."""
        c = self.cat_de_sku
        lp = np.log(precio / self.precio_ref)
        x_cruz = lp @ self.peso_cruz.T
        prof_1 = np.vstack([np.zeros((1, prof.shape[1])), prof[:-1]])
        prof_2 = np.vstack([np.zeros((2, prof.shape[1])), prof[:-2]])
        comun = (self.log_base + self.cruz[c] * x_cruz + self.enc[c] * encarte
                 + self.post[c] * (prof_1 + 0.5 * prof_2))
        propio = self.elasticidad * lp
        return (self.log_tienda[:, None, None] + comun[None]
                + self.sens_tienda[:, None, None] * propio[None])


def _redondear_precio(x):
    # precios de góndola terminados en .x0 o .x9
    return np.round(np.floor(x * 10) / 10 - 0.01 * (x > 15), 2)


def _calendario(rng, semanas: pd.DatetimeIndex, cats: list[str], skus: pd.DataFrame) -> pd.DataFrame:
    """Calendario de promociones con la lógica del área comercial actual."""
    filas = []
    sem = np.arange(len(semanas))
    mes = semanas.month.to_numpy()
    for ci, cat in enumerate(cats):
        temporada = np.zeros(len(semanas), bool)
        if cat in ("Gaseosas", "Cervezas"):
            temporada = np.isin(mes, [12, 1, 2, 3, 7])
        elif cat in ("Aceites", "Arroz"):
            temporada = np.isin(mes, [7, 12])
        ids = skus.loc[skus.categoria == cat, "id_sku"].to_numpy()
        prob_sku = PARTICIPACION ** 0.6 / (PARTICIPACION ** 0.6).sum()
        t = int(rng.integers(0, 4))
        while t < len(semanas) - 1:
            dur = 1 if rng.random() < 0.6 else 2
            dur = min(dur, len(semanas) - t)
            k = int(rng.choice(len(ids), p=prob_sku))
            propia = skus.loc[skus.id_sku == ids[k], "marca_propia"].item()
            aporte = 0.0 if propia or rng.random() > 0.7 else float(rng.choice([0.5, 0.6, 0.7, 0.8, 1.0]))
            # con aporte del proveedor el comprador se anima a un descuento mayor
            p_desc = np.array([0.22, 0.30, 0.26, 0.14, 0.06, 0.02])
            if aporte > 0:
                p_desc = np.array([0.02, 0.10, 0.22, 0.30, 0.22, 0.14])
            desc = float(rng.choice([0.10, 0.15, 0.20, 0.25, 0.30, 0.35], p=p_desc))
            encarte = bool(rng.random() < 0.65)
            filas.append(dict(id_sku=ids[k], i_ini=t, semanas=dur, descuento=desc,
                              encarte=encarte, aporte_proveedor_pct=aporte, ci=ci))
            t += dur
            hueco = int(rng.integers(2, 4)) if temporada[min(t, len(sem) - 1)] else int(rng.integers(2, 7))
            t += hueco
    promos = pd.DataFrame(filas).sort_values(["i_ini", "id_sku"]).reset_index(drop=True)
    promos.insert(0, "id_promo", [f"P{i + 1:03d}" for i in range(len(promos))])
    return promos


def _estacionalidad(semanas: pd.DatetimeIndex, cats: list[str]) -> np.ndarray:
    """Efecto de calendario por categoría (T, C) en escala log."""
    doy = semanas.dayofyear.to_numpy() + 3
    mes = semanas.month.to_numpy()
    dia = (semanas + pd.Timedelta(days=3)).day.to_numpy()
    grati = ((mes == 7) & (dia >= 13)) | ((mes == 12) & (dia >= 13))
    fiestas = (mes == 7) & (dia >= 22)
    fin_anio = (mes == 12) & (dia >= 20)
    verano = np.cos(2 * np.pi * (doy - 45) / 365.25)
    ef = np.zeros((len(semanas), len(cats)))
    for ci, cat in enumerate(cats):
        e = 0.09 * grati
        if cat == "Gaseosas":
            e = e + 0.24 * verano + 0.20 * fin_anio + 0.10 * fiestas
        elif cat == "Cervezas":
            e = e + 0.14 * verano + 0.35 * fiestas + 0.30 * fin_anio
        elif cat == "Yogures":
            e = e - 0.05 * verano
        elif cat == "Galletas":
            e = e - 0.13 * np.isin(mes, [1, 2]) + 0.05 * np.isin(mes, [3, 4])
        elif cat in ("Aceites", "Arroz"):
            e = e + 0.08 * fin_anio
        ef[:, ci] = e
    return ef


def generar(ruta: str | Path, escala: float = 1.0, seed: int = 42) -> Path:
    """Escribe la base DuckDB en `ruta`. `escala` reduce la cantidad de locales."""
    rng = np.random.default_rng(seed)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        ruta.unlink()

    semanas = pd.date_range(INICIO, periods=N_SEMANAS, freq="7D")
    cats = list(CATEGORIAS)

    # --- locales
    tiendas = pd.DataFrame(TIENDAS, columns=["nombre", "distrito", "formato"])
    if escala < 1:
        elegidas = []
        for f in ("Hiper", "Super", "Express"):
            sub = tiendas[tiendas.formato == f]
            elegidas.append(sub.head(max(1, round(len(sub) * escala))))
        tiendas = pd.concat(elegidas)
    tiendas = tiendas.reset_index(drop=True)
    tiendas.insert(0, "id_tienda", [f"T{i + 1:02d}" for i in range(len(tiendas))])
    log_tienda = np.log(tiendas.formato.map(VOLUMEN_FORMATO).to_numpy()) + rng.normal(0, 0.12, len(tiendas))
    sens_tienda = tiendas.formato.map(SENSIBILIDAD_FORMATO).to_numpy() * rng.normal(1, 0.04, len(tiendas))

    # --- productos
    filas = []
    for ci, cat in enumerate(cats):
        p = CATEGORIAS[cat]
        for k, desc in enumerate(MARCAS[cat]):
            propia = desc.startswith("Qollqa")
            filas.append(dict(
                id_sku=f"{ci + 1}{k + 1:02d}", descripcion=desc, marca=desc.split(" ")[0],
                categoria=cat, marca_propia=propia,
                precio_inicial=_redondear_precio(p["precio"] * PRECIO_RELATIVO[k] * rng.normal(1, 0.03)),
                margen=p["margen"] + (0.06 if propia else 0) + rng.normal(0, 0.015),
                base=p["base"] * PARTICIPACION[k] / PARTICIPACION.mean() * rng.lognormal(0, 0.1),
                elasticidad=p["e"] + rng.normal(0, 0.3) - (0.25 if propia else 0),
                ci=ci,
            ))
    skus = pd.DataFrame(filas)
    P, T, C, S = len(skus), len(semanas), len(cats), len(tiendas)
    ci_sku = skus.ci.to_numpy()

    # --- precios regulares: dos o tres alzas en el periodo
    reg = np.tile(skus.precio_inicial.to_numpy(), (T, 1)).astype(float)
    for i in range(P):
        for t0 in sorted(rng.choice(np.arange(8, T - 4), size=int(rng.integers(2, 4)), replace=False)):
            reg[t0:, i] = _redondear_precio(reg[t0, i] * (1 + rng.uniform(0.03, 0.08)) + 0.05)
    costo = reg * (1 - skus.margen.to_numpy())

    # --- promociones
    promos = _calendario(rng, semanas, cats, skus)
    idx = {s: i for i, s in enumerate(skus.id_sku)}
    precio = reg.copy()
    encarte = np.zeros((T, P))
    aporte = np.zeros((T, P))
    for r in promos.itertuples():
        i, sl = idx[r.id_sku], slice(r.i_ini, r.i_ini + r.semanas)
        precio[sl, i] = _redondear_precio(reg[sl, i] * (1 - r.descuento) + 0.05)
        encarte[sl, i] = float(r.encarte)
        aporte[sl, i] = (reg[sl, i] - precio[sl, i]) * r.aporte_proveedor_pct
    prof = 1 - precio / reg

    # --- demanda
    t_anios = np.arange(T) / 52
    tendencia = rng.normal(0.02, 0.04, C)
    estac = _estacionalidad(semanas, cats)
    log_base = (np.log(skus.base.to_numpy())[None, :] + estac[:, ci_sku]
                + tendencia[ci_sku][None, :] * t_anios[:, None]
                + rng.normal(0, 0.04, (T, P)).cumsum(0) * 0.25)  # deriva lenta de cada marca
    peso = np.zeros((P, P))
    base = skus.base.to_numpy()
    for i in range(P):
        otros = (ci_sku == ci_sku[i]) & (np.arange(P) != i)
        peso[i, otros] = base[otros] / base[otros].sum()
    verdad = Verdad(
        cat_de_sku=ci_sku, log_base=log_base, log_tienda=log_tienda, sens_tienda=sens_tienda,
        elasticidad=skus.elasticidad.to_numpy(),
        cruz=np.array([CATEGORIAS[c]["cruz"] for c in cats]) * rng.normal(1, 0.08, C),
        enc=np.array([CATEGORIAS[c]["enc"] for c in cats]),
        post=np.array([CATEGORIAS[c]["post"] for c in cats]),
        precio_ref=skus.precio_inicial.to_numpy(), peso_cruz=peso,
    )
    choque = rng.normal(0, 0.06, (T, P))  # choque común a todos los locales (clima, competencia)
    mu = np.exp(verdad.log_mu(precio, encarte, prof) + choque[None])
    phi = 30.0
    unidades = rng.poisson(rng.gamma(phi, mu / phi))

    # --- verdad por promoción: margen incremental con el descuento real y con otros
    verdad_promos = []
    for r in promos.itertuples():
        for d in sorted(set(DESCUENTOS_GRILLA) | {r.descuento}):
            v = _incremental(verdad, reg, costo, precio, encarte, aporte, r, d, idx)
            v.update(id_promo=r.id_promo, descuento=d, es_real=bool(np.isclose(d, r.descuento)))
            verdad_promos.append(v)
    verdad_promos = pd.DataFrame(verdad_promos)

    # --- tablas
    precios = pd.DataFrame({
        "semana": np.repeat(semanas.date, P), "id_sku": np.tile(skus.id_sku, T),
        "precio_regular": reg.ravel().round(2), "precio_venta": precio.ravel().round(2),
        "costo_unitario": costo.ravel().round(4), "encarte": encarte.ravel().astype(bool),
        "aporte_unitario": aporte.ravel().round(4),
    })
    ventas = pd.DataFrame({
        "semana": np.tile(np.repeat(semanas.date, P), S),
        "id_tienda": np.repeat(tiendas.id_tienda, T * P),
        "id_sku": np.tile(skus.id_sku, S * T),
        "unidades": unidades.ravel().astype(int),
    })
    promos_out = promos.assign(
        inicio=semanas[promos.i_ini].date,
        fin=(semanas[promos.i_ini + promos.semanas - 1] + pd.Timedelta(days=6)).date,
    )[["id_promo", "id_sku", "inicio", "fin", "semanas", "descuento", "encarte", "aporte_proveedor_pct"]]
    productos = skus[["id_sku", "descripcion", "marca", "categoria", "marca_propia"]]
    aux_sku = skus[["id_sku", "elasticidad"]].assign(
        cruz=verdad.cruz[ci_sku], post=verdad.post[ci_sku], enc=verdad.enc[ci_sku])
    aux_tienda = tiendas[["id_tienda"]].assign(sensibilidad=sens_tienda)

    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in [("tiendas", tiendas), ("productos", productos), ("precios_semana", precios),
                           ("ventas_semana", ventas), ("promociones", promos_out),
                           ("aux_promo_verdad", verdad_promos), ("aux_sku_verdad", aux_sku),
                           ("aux_tienda_verdad", aux_tienda)]:
            con.register("t", df)
            con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM t")
            con.unregister("t")
        con.execute("COMMENT ON TABLE aux_promo_verdad IS 'Solo para evaluar: margen incremental real'")
    finally:
        con.close()
    return ruta


def _incremental(verdad: Verdad, reg, costo, precio, encarte, aporte, promo, descuento, idx) -> dict:
    """Unidades y margen con la promoción menos sin ella, en la categoría, durante y después."""
    i = idx[promo.id_sku]
    ini, fin = promo.i_ini, promo.i_ini + promo.semanas
    ventana = slice(ini, min(fin + VENTANA_POST, reg.shape[0]))
    cat = verdad.cat_de_sku == verdad.cat_de_sku[i]

    def escenario(d):
        p, e, a = precio.copy(), encarte.copy(), aporte.copy()
        if not np.isclose(d, promo.descuento):  # con el descuento real se usa el precio de góndola
            p[ini:fin, i] = reg[ini:fin, i] * (1 - d) if d > 0 else reg[ini:fin, i]
        e[ini:fin, i] = float(promo.encarte) if d > 0 else 0.0
        a[ini:fin, i] = (reg[ini:fin, i] - p[ini:fin, i]) * promo.aporte_proveedor_pct
        prof = 1 - p / reg
        u = np.exp(verdad.log_mu(p, e, prof)).sum(0)  # (T, P), suma de locales
        return u, p, a

    u1, p1, a1 = escenario(descuento)
    u0, p0, a0 = escenario(0.0)
    m1 = (u1 * (p1 - costo + a1))[ventana][:, cat].sum()
    m0 = (u0 * (p0 - costo + a0))[ventana][:, cat].sum()
    du = (u1 - u0)[ventana]
    propio = du[: fin - ini, i].sum()
    otros = np.where(cat)[0]
    otros = otros[otros != i]
    return dict(
        unid_propias=float(propio),
        unid_canibalizadas=float(du[: fin - ini][:, otros].sum()),
        unid_post=float(du[fin - ini:][:, cat].sum()),
        venta_incremental=float(((u1 * p1)[ventana][:, cat].sum() - (u0 * p0)[ventana][:, cat].sum())),
        margen_incremental=float(m1 - m0),
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--salida", default=str(Path(__file__).parent / "qollqa.duckdb"))
    a = ap.parse_args()
    print(generar(a.salida, a.escala, a.seed))
