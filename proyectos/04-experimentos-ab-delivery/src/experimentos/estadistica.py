"""
Comparaciones entre control y tratamiento: diferencia de medias (Welch), CUPED,
método delta para métricas de ratio, chequeo de SRM, Benjamini-Hochberg y MDE.

Todo devuelve el efecto absoluto y el relativo con su intervalo; el relativo es el
que se reporta, porque "+2.1% de pedidos" se entiende sin conocer la media.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats


@dataclass
class Comparacion:
    metodo: str
    n_control: int
    n_tratamiento: int
    media_control: float
    media_tratamiento: float
    diferencia: float
    error_estandar: float
    p_valor: float
    relativo: float
    relativo_bajo: float
    relativo_alto: float
    reduccion_varianza: float = 0.0

    @property
    def significativo(self) -> bool:
        return self.p_valor < 0.05

    def a_dict(self) -> dict:
        return asdict(self)


def _z(alfa: float = 0.05) -> float:
    return stats.norm.ppf(1 - alfa / 2)


def _relativo(mt, mc, var_mt, var_mc, alfa=0.05):
    """Lift relativo mt/mc - 1 con IC por método delta."""
    r = mt / mc - 1
    ee = np.sqrt(var_mt / mc**2 + mt**2 * var_mc / mc**4)
    return r, r - _z(alfa) * ee, r + _z(alfa) * ee


def comparar_medias(y: np.ndarray, t: np.ndarray, alfa: float = 0.05, metodo: str = "welch",
                    media_ref: tuple[float, float] | None = None) -> Comparacion:
    y, t = np.asarray(y, float), np.asarray(t, bool)
    yc, yt = y[~t], y[t]
    mc, mt = yc.mean(), yt.mean()
    vc, vt = yc.var(ddof=1) / len(yc), yt.var(ddof=1) / len(yt)
    ee = np.sqrt(vc + vt)
    dif = mt - mc
    p = 2 * stats.norm.sf(abs(dif) / ee) if ee > 0 else 1.0
    # con CUPED las medias ajustadas cambian de nivel; el relativo se mide sobre la media real
    if media_ref is not None:
        mc_ref, _ = media_ref
        r = dif / mc_ref
        rb, ra = r - _z(alfa) * ee / mc_ref, r + _z(alfa) * ee / mc_ref
        mc, mt = media_ref
    else:
        r, rb, ra = _relativo(mt, mc, vt, vc, alfa)
    return Comparacion(metodo, len(yc), len(yt), mc, mt, dif, ee, p, r, rb, ra)


def theta_cuped(y: np.ndarray, x: np.ndarray) -> float:
    vx = np.var(x, ddof=1)
    return 0.0 if vx == 0 else float(np.cov(y, x, ddof=1)[0, 1] / vx)


def cuped(y: np.ndarray, x: np.ndarray, t: np.ndarray, alfa: float = 0.05) -> Comparacion:
    """
    CUPED (Deng et al., 2013): y - θ(x - x̄), con θ estimado en las dos variantes juntas.
    No cambia el efecto esperado (x es previo al experimento) y baja la varianza en ρ².
    """
    y, x, t = np.asarray(y, float), np.asarray(x, float), np.asarray(t, bool)
    th = theta_cuped(y, x)
    y_adj = y - th * (x - x.mean())
    c = comparar_medias(y_adj, t, alfa, "cuped", media_ref=(y[~t].mean(), y[t].mean()))
    c.reduccion_varianza = float(1 - np.var(y_adj, ddof=1) / np.var(y, ddof=1)) if np.var(y) > 0 else 0.0
    return c


def _ratio(num, den):
    """Ratio de sumas y su varianza por método delta (unidad de aleatorización: usuario)."""
    n = len(num)
    mn, md = num.mean(), den.mean()
    cov = np.cov(num, den, ddof=1)
    var = (cov[0, 0] / md**2 - 2 * mn * cov[0, 1] / md**3 + mn**2 * cov[1, 1] / md**4) / n
    return mn / md, var


def comparar_ratio(num: np.ndarray, den: np.ndarray, t: np.ndarray, alfa: float = 0.05) -> Comparacion:
    """
    Métricas como ticket promedio (GMV / pedidos): el pedido no es independiente, el
    usuario sí. Tratar cada pedido como observación subestima la varianza.
    """
    num, den, t = np.asarray(num, float), np.asarray(den, float), np.asarray(t, bool)
    rc, vc = _ratio(num[~t], den[~t])
    rt, vt = _ratio(num[t], den[t])
    ee = np.sqrt(vc + vt)
    dif = rt - rc
    p = 2 * stats.norm.sf(abs(dif) / ee) if ee > 0 else 1.0
    r, rb, ra = _relativo(rt, rc, vt, vc, alfa)
    return Comparacion("delta", int((~t).sum()), int(t.sum()), rc, rt, dif, ee, p, r, rb, ra)


def srm(n_control: int, n_tratamiento: int, reparto_tratamiento: float = 0.5) -> float:
    """p-valor chi-cuadrado de Sample Ratio Mismatch. Bajo 0.001 la asignación no es confiable."""
    n = n_control + n_tratamiento
    esperado = [n * (1 - reparto_tratamiento), n * reparto_tratamiento]
    return float(stats.chisquare([n_control, n_tratamiento], esperado).pvalue)


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """q-valores de Benjamini-Hochberg (controla la tasa de falsos descubrimientos)."""
    p = np.asarray(p, float)
    n = len(p)
    orden = np.argsort(p)
    q = p[orden] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    salida = np.empty(n)
    salida[orden] = np.minimum(q, 1.0)
    return salida


def mde_relativo(media: float, sd: float, n_por_grupo: float, rho: float = 0.0,
                 alfa: float = 0.05, potencia: float = 0.8) -> float:
    """Efecto mínimo detectable (relativo a la media) con n usuarios por grupo."""
    z = _z(alfa) + stats.norm.ppf(potencia)
    return float(z * sd * np.sqrt(2 * (1 - rho**2) / n_por_grupo) / media)


def n_necesario(media: float, sd: float, mde: float, rho: float = 0.0,
                alfa: float = 0.05, potencia: float = 0.8) -> int:
    """Usuarios por grupo para detectar un efecto relativo `mde`."""
    z = _z(alfa) + stats.norm.ppf(potencia)
    return int(np.ceil(2 * (z * sd / (mde * media)) ** 2 * (1 - rho**2)))
