"""
Simulador de promociones: margen incremental de la categoría con la posterior.

Compara dos escenarios con las mismas semanas: el producto en promoción y el
producto a precio regular. La diferencia se suma en todas las marcas de la
categoría, durante la promoción y las dos semanas siguientes, así entran la
canibalización y la caída posterior. Cada draw de la posterior da un margen
incremental; con eso salen la media, el intervalo y la probabilidad de ganar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .consultas import Matrices
from .modelo import Meta, log_mu, rasgos

VENTANA_POST = 2
DESCUENTOS = (0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35)


@dataclass
class Escenario:
    id_sku: str
    inicio: pd.Timestamp
    semanas: int
    descuento: float
    encarte: bool
    aporte_pct: float


class Simulador:
    def __init__(self, post: dict, meta: Meta, m: Matrices, semanas_futuras: int = 16,
                 n_draws: int = 400, seed: int = 0):
        rng = np.random.default_rng(seed)
        D = post["e"].shape[0]
        elegidos = rng.choice(D, size=min(n_draws, D), replace=False)
        self.post = {k: v[elegidos] for k, v in post.items()}
        self.meta = meta
        self.skus = list(m.skus.id_sku)
        self.cat = m.cat_de_sku

        # se extiende el calendario con semanas futuras a precio regular vigente
        extra = pd.date_range(m.semanas[-1] + pd.Timedelta(days=7), periods=semanas_futuras, freq="7D")
        self.semanas = m.semanas.append(extra)

        def extender(x, valor=None):
            cola = np.repeat(x[-1:], semanas_futuras, 0) if valor is None else np.full((semanas_futuras, x.shape[1]), valor)
            return np.vstack([x, cola])

        self.regular = extender(m.regular)
        self.costo = extender(m.costo)
        self.precio = np.vstack([m.precio, self.regular[len(m.semanas):]])
        self.encarte = extender(m.encarte, 0.0)
        self.aporte = extender(m.aporte, 0.0)
        self.ultima_observada = m.semanas[-1]

    # ------------------------------------------------------------------ escenarios

    def _semana(self, fecha) -> int:
        pos = self.semanas.get_indexer([pd.Timestamp(fecha)])[0]
        if pos < 0:
            raise ValueError(f"La semana {fecha} no está en el calendario")
        return int(pos)

    def _margen(self, precio, encarte, aporte, idx_t, idx_p):
        r = rasgos(self.meta, self.semanas, precio, self.regular, encarte)
        u = np.exp(log_mu(self.post, r, self.meta, idx_t, idx_p)).sum(1)  # (D, T, P) suma de formatos
        sel = np.ix_(idx_t, idx_p)
        margen = (u * (precio[sel] - self.costo[sel] + aporte[sel])).sum((1, 2))
        venta = (u * precio[sel]).sum((1, 2))
        return u, margen, venta

    def simular(self, esc: Escenario) -> dict[str, np.ndarray]:
        """Draws de margen, venta y unidades incrementales del escenario frente a no hacer la promoción."""
        i = self.skus.index(esc.id_sku)
        ini = self._semana(esc.inicio)
        fin = min(ini + esc.semanas, len(self.semanas))
        idx_t = np.arange(ini, min(fin + VENTANA_POST, len(self.semanas)))
        idx_p = np.where(self.cat == self.cat[i])[0]
        k = int(np.where(idx_p == i)[0][0])

        # escenario sin promoción: el producto a precio regular en esas semanas
        p0, e0, a0 = self.precio.copy(), self.encarte.copy(), self.aporte.copy()
        p0[ini:fin, i] = self.regular[ini:fin, i]
        e0[ini:fin, i] = 0.0
        a0[ini:fin, i] = 0.0
        p1, e1, a1 = p0.copy(), e0.copy(), a0.copy()
        if esc.descuento > 0:
            p1[ini:fin, i] = self.regular[ini:fin, i] * (1 - esc.descuento)
            e1[ini:fin, i] = float(esc.encarte)
            a1[ini:fin, i] = self.regular[ini:fin, i] * esc.descuento * esc.aporte_pct

        u0, m0, v0 = self._margen(p0, e0, a0, idx_t, idx_p)
        u1, m1, v1 = self._margen(p1, e1, a1, idx_t, idx_p)
        du = u1 - u0
        n = fin - ini
        otros = np.arange(len(idx_p)) != k
        return dict(
            margen_incremental=m1 - m0,
            venta_incremental=v1 - v0,
            unid_propias=du[:, :n, k].sum(1),
            unid_canibalizadas=du[:, :n][:, :, otros].sum((1, 2)),
            unid_post=du[:, n:].sum((1, 2)),
            margen_base=m0,
        )

    def resumir(self, esc: Escenario) -> dict:
        s = self.simular(esc)
        m = s["margen_incremental"]
        return dict(
            margen_media=float(m.mean()), margen_p05=float(np.percentile(m, 5)),
            margen_p95=float(np.percentile(m, 95)), prob_gana=float((m > 0).mean()),
            venta_media=float(s["venta_incremental"].mean()),
            unid_propias=float(s["unid_propias"].mean()),
            unid_canibalizadas=float(s["unid_canibalizadas"].mean()),
            unid_post=float(s["unid_post"].mean()),
        )

    def curva(self, esc: Escenario, descuentos=DESCUENTOS) -> pd.DataFrame:
        """Margen incremental esperado para cada profundidad de descuento."""
        filas = []
        for d in descuentos:
            r = self.resumir(Escenario(esc.id_sku, esc.inicio, esc.semanas, d, esc.encarte, esc.aporte_pct))
            filas.append(dict(descuento=d, **r))
        return pd.DataFrame(filas)

    def recomendar(self, esc: Escenario, descuentos=DESCUENTOS, prob_minima: float = 0.6) -> dict:
        """El descuento con mayor margen esperado entre los que ganan con probabilidad suficiente."""
        c = self.curva(esc, descuentos)
        validos = c[(c.descuento == 0) | (c.prob_gana >= prob_minima)]
        mejor = validos.loc[validos.margen_media.idxmax()]
        return dict(descuento=float(mejor.descuento), margen_media=float(mejor.margen_media),
                    prob_gana=float(mejor.prob_gana), curva=c)
