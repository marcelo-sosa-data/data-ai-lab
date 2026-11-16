"""
Modelo bayesiano jerárquico de demanda semanal por formato de tienda y producto.

    log E[unidades] = intercepto(formato, sku)
                    + tendencia(cat) + calendario(cat)
                    + exp(ajuste(formato)) * [ elasticidad al descuento(sku) * log(precio / regular)
                                             + elasticidad al precio regular(cat) * log(regular / referencia) ]
                    + sustitución(cat) * descuento de las otras marcas de la categoría
                    + encarte(cat) + caída post-promoción(cat) por profundidad de descuento rezagada

La elasticidad al descuento de cada producto sale de una normal con media y
dispersión propias de su categoría (pooling parcial): un producto con pocas
promociones se apoya en las demás marcas de su categoría. La del precio regular
va aparte, por categoría, porque las alzas de lista son pocas y coinciden con
cambios lentos de la marca que no tienen que ver con el precio. La verosimilitud
es binomial negativa.

La predicción con la posterior se hace en numpy (`log_mu`), con la misma fórmula,
para que el simulador corra en milisegundos sin volver a muestrear.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .consultas import FORMATOS, Matrices

NOMBRES_CALENDARIO = ["sen1", "cos1", "sen2", "cos2", "gratificacion", "fiestas_patrias", "fin_de_anio"]
PARAMETROS = ["a", "tend", "cal", "e", "e_reg", "dfmt", "cruz", "enc", "post1", "post2", "alpha",
              "mu_e", "sd_e"]


def calendario(semanas: pd.DatetimeIndex) -> np.ndarray:
    """Fourier anual de dos armónicos y banderas de gratificación, Fiestas Patrias y fin de año."""
    medio = pd.DatetimeIndex(semanas) + pd.Timedelta(days=3)
    x = 2 * np.pi * medio.dayofyear.to_numpy() / 365.25
    mes, dia = medio.month.to_numpy(), medio.day.to_numpy()
    return np.column_stack([
        np.sin(x), np.cos(x), np.sin(2 * x), np.cos(2 * x),
        ((mes == 7) | (mes == 12)) & (dia >= 13),
        (mes == 7) & (dia >= 22),
        (mes == 12) & (dia >= 20),
    ]).astype(float)


@dataclass
class Meta:
    """Lo que el modelo necesita para armar rasgos fuera de la muestra."""

    skus: list[str]
    categorias: list[str]
    cat_de_sku: list[int]
    regular_ref: list[float]
    peso_cruz: list[list[float]]
    log_media: list[list[float]]  # (F, P)
    inicio: str
    t_medio: float
    semanas_ajuste: int

    @classmethod
    def desde(cls, m: Matrices) -> "Meta":
        c = m.cat_de_sku
        P = len(c)
        sin_promo = m.precio >= m.regular - 1e-9
        u_total = m.unidades.sum(0)
        base = np.array([u_total[sin_promo[:, i], i].mean() for i in range(P)])
        peso = np.zeros((P, P))
        for i in range(P):
            otros = (c == c[i]) & (np.arange(P) != i)
            peso[i, otros] = base[otros] / base[otros].sum()
        log_media = np.log(np.maximum(m.unidades.mean(1), 1.0))
        # referencia = media geométrica del precio regular en el ajuste: log(regular/ref) queda
        # centrado y el intercepto no se correlaciona con la elasticidad al precio regular
        regular_ref = np.exp(np.log(m.regular).mean(0))
        t_medio = float((m.semanas - m.semanas[0]).days.to_numpy().mean() / 364.0)
        return cls(list(m.skus.id_sku), m.categorias, c.tolist(), regular_ref.tolist(),
                   peso.tolist(), log_media.tolist(), str(m.semanas[0].date()), t_medio, len(m.semanas))


def rasgos(meta: Meta, semanas: pd.DatetimeIndex, precio: np.ndarray, regular: np.ndarray,
           encarte: np.ndarray) -> dict[str, np.ndarray]:
    """Variables explicativas en forma (semana, sku); `cal` es (semana, k) y `t` en años."""
    ld = np.log(precio / regular)                      # 0 a precio regular, negativo en promoción
    lr = np.log(regular / np.asarray(meta.regular_ref))
    prof = np.clip(1 - precio / regular, 0, None)
    ceros = np.zeros((1, prof.shape[1]))
    t = (pd.DatetimeIndex(semanas) - pd.Timestamp(meta.inicio)).days.to_numpy() / 364.0 - meta.t_medio
    return dict(
        ld=ld, lr=lr, xc=ld @ np.asarray(meta.peso_cruz).T, enc=np.asarray(encarte, float),
        p1=np.vstack([ceros, prof[:-1]]), p2=np.vstack([ceros, ceros, prof[:-2]]),
        cal=calendario(semanas), t=t,
    )


def log_mu(post: dict[str, np.ndarray], r: dict[str, np.ndarray], meta: Meta,
           idx_t: np.ndarray | None = None, idx_p: np.ndarray | None = None) -> np.ndarray:
    """Log de la demanda esperada por draw: (D, F, T, P) para las semanas y skus pedidos."""
    idx_t = np.arange(r["ld"].shape[0]) if idx_t is None else np.asarray(idx_t)
    idx_p = np.arange(r["ld"].shape[1]) if idx_p is None else np.asarray(idx_p)
    c = np.asarray(meta.cat_de_sku)[idx_p]
    sel = np.ix_(idx_t, idx_p)
    ld, lr, xc, enc, p1, p2 = (r[k][sel] for k in ("ld", "lr", "xc", "enc", "p1", "p2"))
    cal, t = r["cal"][idx_t], r["t"][idx_t]

    comun = (post["tend"][:, c][:, None, :] * t[None, :, None]
             + np.einsum("tk,dpk->dtp", cal, post["cal"][:, c, :])
             + post["cruz"][:, c][:, None, :] * xc[None]
             + post["enc"][:, c][:, None, :] * enc[None]
             + post["post1"][:, c][:, None, :] * p1[None]
             + post["post2"][:, c][:, None, :] * p2[None])           # (D, T, P)
    propio = (post["e"][:, idx_p][:, None, :] * ld[None]
              + post["e_reg"][:, c][:, None, :] * lr[None])           # (D, T, P)
    ajuste = np.exp(post["dfmt"])                                     # (D, F)
    return (post["a"][:, :, idx_p][:, :, None, :] + comun[:, None]
            + ajuste[:, :, None, None] * propio[:, None])


def construir(m: Matrices, meta: Meta, con_mu: bool = False):
    """Modelo PyMC sobre (formato, semana, sku) desde la tercera semana (las dos primeras no tienen rezagos)."""
    import pymc as pm
    import pytensor.tensor as pt

    r = rasgos(meta, m.semanas, m.precio, m.regular, m.encarte)
    F, T, P = m.unidades.shape
    c = np.asarray(meta.cat_de_sku)
    # todo en tensores densos (formato, semana, sku): el gradiente sale mucho más rápido que con índices
    ts = slice(2, T)
    y = m.unidades[:, ts].astype(int)
    ld, lr, xc, enc_x, p1, p2 = (r[k][ts] for k in ("ld", "lr", "xc", "enc", "p1", "p2"))
    cal, t = r["cal"][ts], r["t"][ts]

    coords = {"formato": FORMATOS, "sku": meta.skus, "categoria": meta.categorias,
              "calendario": NOMBRES_CALENDARIO}
    with pm.Model(coords=coords) as modelo:
        a = pm.Normal("a", mu=np.asarray(meta.log_media), sigma=1.0, dims=("formato", "sku"))
        tend = pm.Normal("tend", 0, 0.2, dims="categoria")
        b_cal = pm.Normal("cal", 0, 0.3, dims=("categoria", "calendario"))
        mu_e = pm.Normal("mu_e", -1.5, 1.0, dims="categoria")
        sd_e = pm.HalfNormal("sd_e", 0.5, dims="categoria")
        z_e = pm.Normal("z_e", 0, 1, dims="sku")
        e = pm.Deterministic("e", mu_e[c] + sd_e[c] * z_e, dims="sku")
        e_reg = pm.Normal("e_reg", -1.0, 0.7, dims="categoria")
        d_hiper = pm.Normal("d_hiper", 0, 0.3)
        d_express = pm.Normal("d_express", 0, 0.3)
        dfmt = pm.Deterministic("dfmt", pt.stack([d_hiper, pt.constant(0.0), d_express]), dims="formato")
        cruz = pm.HalfNormal("cruz", 1.5, dims="categoria")
        enc = pm.Normal("enc", 0, 0.3, dims="categoria")
        post1 = pm.Normal("post1", 0, 1.0, dims="categoria")
        post2 = pm.Normal("post2", 0, 1.0, dims="categoria")
        alpha = pm.Gamma("alpha", 2.0, 0.02)

        comun = (tend[c][None, :] * t[:, None] + pt.dot(cal, b_cal[c].T)
                 + cruz[c][None, :] * xc + enc[c][None, :] * enc_x
                 + post1[c][None, :] * p1 + post2[c][None, :] * p2)          # (T, P)
        propio = e[None, :] * ld + e_reg[c][None, :] * lr                    # (T, P)
        eta = a[:, None, :] + comun[None] + pt.exp(dfmt)[:, None, None] * propio[None]
        if con_mu:
            pm.Deterministic("eta", eta)
        pm.NegativeBinomial("y", mu=pt.exp(eta), alpha=alpha, observed=y)
    return modelo


def ajustar(m: Matrices, draws: int = 500, tune: int = 600, chains: int = 2, seed: int = 13):
    """Muestrea la posterior con NUTS (nutpie). Devuelve (posterior en arrays, meta, diagnóstico)."""
    import arviz as az
    import pymc as pm

    meta = Meta.desde(m)
    modelo = construir(m, meta)
    with modelo:
        traza = pm.sample(draws=draws, tune=tune, chains=chains, random_seed=seed,
                          nuts_sampler="nutpie", cores=chains, target_accept=0.95,
                          progressbar=False)
    posterior = traza.posterior
    post = {}
    for k in PARAMETROS:
        x = posterior[k].to_numpy()
        post[k] = x.reshape((-1,) + x.shape[2:])
    resumen = az.summary(traza, var_names=["mu_e", "e", "cruz", "enc", "post1", "post2", "dfmt"],
                         kind="diagnostics")
    diag = dict(rhat_max=float(np.nanmax(resumen["r_hat"].to_numpy())),
                ess_min=float(np.nanmin(resumen["ess_bulk"].to_numpy())),
                divergencias=int(traza.sample_stats["diverging"].to_numpy().sum()),
                draws=int(post["e"].shape[0]))
    return post, meta, diag


def guardar(carpeta: Path, nombre: str, post: dict, meta: Meta, diag: dict) -> None:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(carpeta / f"{nombre}.npz", **post)
    (carpeta / f"{nombre}.json").write_text(json.dumps({"meta": asdict(meta), "diag": diag}), encoding="utf-8")


def cargar(carpeta: Path, nombre: str) -> tuple[dict, Meta, dict]:
    carpeta = Path(carpeta)
    with np.load(carpeta / f"{nombre}.npz") as z:
        post = {k: z[k] for k in z.files}
    info = json.loads((carpeta / f"{nombre}.json").read_text(encoding="utf-8"))
    return post, Meta(**info["meta"]), info["diag"]
