"""
¿Por qué se movió una métrica? Descompone el cambio por cada dimensión y ordena las
dimensiones según qué tan concentrado está el cambio.

Métricas aditivas (TPV, transacciones): la contribución de cada segmento es su
variación absoluta.

Ratios (tasa de aprobación, ticket, take rate): con r = N/D y w_i = D_i/D,

    Δr = Σ (w1_i - w0_i)·(r0_i - r0)   efecto mezcla: cambió el peso de los segmentos
       + Σ w1_i·(r1_i - r0_i)          efecto tasa: cambió el valor dentro del segmento

La identidad es exacta. Un segmento que no existía en la base (una versión nueva de la
app, los comercios de una campaña) toma r0_i = r1_i: lo que aporta es mezcla pura.

Concentración de una dimensión = Σ_{i∈S} (c_i - w_i·Δ) / Σ_j |c_j|, con S el grupo
mínimo de segmentos que lleva el cambio: cuánto se apartan de lo que les tocaría si el
cambio se repartiera según su peso, sobre todo lo que se movió en esa dimensión. 0: el cambio se reparte como el volumen
(no es un segmento en particular); cerca de 1: casi todo el cambio está en un segmento
chico. Dividir entre Σ|c_j| y no entre Δ evita que explote cuando el total casi no se
mueve porque un segmento cae y otros crecen.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from .calendario import etiqueta_dia
from .capa import CapaSemantica
from .compilador import Consulta
from .modelo import ErrorSemantico

# desde aquí se dice que una dimensión "explica" el cambio; debajo, el cambio está repartido
UMBRAL = 0.4


@dataclass
class Explicacion:
    metrica: str
    descripcion_base: str
    valor_base: float
    valor_actual: float
    ranking: pd.DataFrame            # una fila por dimensión
    detalle: dict[str, pd.DataFrame]  # segmentos de cada dimensión

    @property
    def cambio(self) -> float:
        return self.valor_actual - self.valor_base


def _componentes(capa: CapaSemantica, metrica: str) -> tuple[str, str | None]:
    m = capa.definicion.metrica(metrica)
    if m.tipo == "ratio":
        return m.numerador, m.denominador
    if m.tipo == "simple" and capa.definicion.medidas[m.medida].aditiva:
        return m.medida, None
    raise ErrorSemantico(f"{metrica} no se puede descomponer por segmentos "
                         "(solo métricas aditivas o ratios de medidas aditivas)")


def descomponer(base: pd.DataFrame, actual: pd.DataFrame, num: str, den: str | None) -> pd.DataFrame:
    """`base` y `actual` indexados por segmento, con columnas num (y den si es ratio)."""
    seg = base.index.union(actual.index)
    b = base.reindex(seg).fillna(0.0)
    a = actual.reindex(seg).fillna(0.0)
    if den is None:
        c = a[num] - b[num]
        return pd.DataFrame({"peso_base": b[num] / b[num].sum(), "peso_actual": a[num] / a[num].sum(),
                             "valor_base": b[num], "valor_actual": a[num], "efecto_mezcla": 0.0,
                             "efecto_tasa": c, "contribucion": c}, index=seg)
    r0 = b[num].sum() / b[den].sum()
    w0, w1 = b[den] / b[den].sum(), a[den] / a[den].sum()
    r1_i = np.where(a[den] > 0, a[num] / a[den].where(a[den] > 0, 1), np.nan)
    r0_i = np.where(b[den] > 0, b[num] / b[den].where(b[den] > 0, 1), r1_i)
    mezcla = (w1 - w0) * (r0_i - r0)
    tasa = np.where(a[den] > 0, w1 * (r1_i - r0_i), 0.0)
    return pd.DataFrame({"peso_base": w0, "peso_actual": w1, "valor_base": r0_i, "valor_actual": r1_i,
                         "efecto_mezcla": mezcla, "efecto_tasa": tasa, "contribucion": mezcla + tasa}, index=seg)


def _exceso(det: pd.DataFrame) -> pd.Series:
    """Lo que aporta cada segmento por encima de lo que le tocaría según su peso."""
    peso = (det.peso_base + det.peso_actual) / 2
    return det.contribucion - peso * det.contribucion.sum()


def segmentos_clave(det: pd.DataFrame) -> tuple[list, float]:
    """
    Los segmentos que concentran el cambio y la concentración que alcanzan.

    Se ordenan por exceso en la dirección del cambio y se acumulan; se toma el grupo
    más chico que logra el 90% del máximo acumulado. Así una caída entre las 11 y las
    16 horas sale como cinco horas juntas y no como "la hora 13".
    """
    movido = det.contribucion.abs().sum()
    if movido < 1e-12:
        return [], 0.0
    signo = np.sign(det.contribucion.sum()) or 1.0
    exceso = (_exceso(det) * signo).sort_values(ascending=False)
    acumulado = exceso.cumsum().to_numpy()
    k = int(np.argmax(acumulado >= 0.9 * acumulado.max())) + 1
    return list(exceso.index[:k]), float(np.clip(acumulado[k - 1] / movido, 0.0, 1.0))


def concentracion(det: pd.DataFrame) -> float:
    return segmentos_clave(det)[1]


def _resumir(dim: str, det: pd.DataFrame) -> dict:
    total = det.contribucion.sum()
    segs, conc = segmentos_clave(det)
    sel = det.loc[segs] if segs else det.iloc[:0]
    if all(str(x).isdigit() for x in segs):  # horas: en orden, se leen como un rango
        segs = sorted(segs, key=int)
    nombres = ", ".join(map(str, segs[:5])) + (f" y {len(segs) - 5} más" if len(segs) > 5 else "")
    return {"dimension": dim, "concentracion": conc, "segmento": nombres, "n_segmentos": len(segs),
            "contribucion": float(sel.contribucion.sum()),
            "parte_del_cambio": float(sel.contribucion.sum() / total) if total else np.nan,
            "peso_segmento": float(((sel.peso_base + sel.peso_actual) / 2).sum()),
            "efecto_mezcla": float(det.efecto_mezcla.sum()), "efecto_tasa": float(det.efecto_tasa.sum())}


def dimensiones_por_defecto(capa: CapaSemantica, metrica: str) -> list[str]:
    """Las explicables; en métricas aditivas, además, sin las que derivan solas en el tiempo."""
    _, den = _componentes(capa, metrica)
    d = capa.definicion
    return [x for x in d.dimensiones() if d.dimension(x).explicable and (den or not d.dimension(x).deriva)]


def _por_dimension(capa, con, metrica, dims, desde, hasta, filtros) -> dict[str, pd.DataFrame]:
    num, den = _componentes(capa, metrica)
    medidas = [num] + ([den] if den else [])
    salida = {}
    for d in dims:
        df = capa.consultar(con, Consulta(metricas=[metrica], dimensiones=[d], grano="dia", desde=desde,
                                          hasta=hasta, filtros=filtros, incluir_medidas=True))
        salida[d] = df[["periodo", d] + medidas]
    return salida


def explicar_dia(capa: CapaSemantica, con: duckdb.DuckDBPyConnection, metrica: str, fecha,
                 dimensiones: list[str] | None = None, filtros: dict | None = None,
                 semanas: int = 4) -> Explicacion:
    """Compara un día contra el promedio del mismo día de la semana en las `semanas` previas."""
    fecha = pd.Timestamp(fecha)
    base_dias = [fecha - pd.Timedelta(weeks=k) for k in range(1, semanas + 1)]
    return _explicar(capa, con, metrica, [fecha], base_dias, dimensiones, filtros or {},
                     f"promedio de los {semanas} {['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábados', 'domingos'][fecha.dayofweek]} previos")


def explicar_periodos(capa: CapaSemantica, con: duckdb.DuckDBPyConnection, metrica: str,
                      actual: tuple, base: tuple, dimensiones: list[str] | None = None,
                      filtros: dict | None = None) -> Explicacion:
    """Compara dos rangos de fechas (por ejemplo, un mes contra otro)."""
    a = pd.date_range(*actual)
    b = pd.date_range(*base)
    return _explicar(capa, con, metrica, list(a), list(b), dimensiones, filtros or {},
                     f"{etiqueta_dia(b[0], True)} a {etiqueta_dia(b[-1], True)}", promediar_base=False)


def _explicar(capa, con, metrica, dias_actual, dias_base, dims, filtros, descripcion,
              promediar_base: bool = True) -> Explicacion:
    dims = dims or dimensiones_por_defecto(capa, metrica)
    num, den = _componentes(capa, metrica)
    medidas = [num] + ([den] if den else [])
    desde, hasta = min(dias_actual + dias_base).date(), max(dias_actual + dias_base).date()
    datos = _por_dimension(capa, con, metrica, dims, desde, hasta, filtros)

    ranking, detalle = [], {}
    valor_base = valor_actual = None
    for d, df in datos.items():
        a = df[df.periodo.isin(dias_actual)].groupby(d)[medidas].sum()
        b = df[df.periodo.isin(dias_base)].groupby(d)[medidas].sum()
        if promediar_base and den is None:
            b = b / len(dias_base)  # el promedio importa en aditivas; en ratios se cancela
        det = descomponer(b, a, num, den)
        det.index = det.index.astype(str)
        det["parte_del_cambio"] = det.contribucion / det.contribucion.sum()
        detalle[d] = det.sort_values("contribucion", key=lambda s: -s * np.sign(det.contribucion.sum()))
        ranking.append(_resumir(d, det))
        if valor_base is None:
            valor_base = b[num].sum() / (b[den].sum() if den else 1)
            valor_actual = a[num].sum() / (a[den].sum() if den else 1)
    rk = pd.DataFrame(ranking).sort_values("concentracion", ascending=False, ignore_index=True)
    return Explicacion(metrica, descripcion, float(valor_base), float(valor_actual), rk, detalle)
