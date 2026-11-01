"""
Validación de la capa contra la base: que cada tabla y columna exista, que cada
métrica compile y corra, y que las medidas aditivas concilien (el total del periodo
es igual a la suma por cualquier dimensión). Si alguien cambia un join a INNER o
agrega una dimensión que duplica filas, la conciliación lo detecta.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

from .capa import CapaSemantica
from .compilador import SIN_DATO, Consulta

TOLERANCIA = 0.005  # soles: las sumas de DECIMAL cuadran exacto; esto cubre el paso a float


@dataclass
class Chequeo:
    grupo: str
    nombre: str
    ok: bool
    detalle: str = ""


def _columnas(expr: str) -> set[str]:
    return {c.name for c in sqlglot.parse_one(expr, read="duckdb").find_all(exp.Column)}


def chequear_esquema(capa: CapaSemantica, con: duckdb.DuckDBPyConnection) -> list[Chequeo]:
    d = capa.definicion
    tablas = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    salida = []
    for nm, mod in d.modelos.items():
        if mod.tabla not in tablas:
            salida.append(Chequeo("esquema", f"tabla {mod.tabla}", False, "no existe en la base"))
            continue
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [mod.tabla]).fetchall()}
        usadas = {e.columna for e in mod.entidades.values()} | ({mod.tiempo} if mod.tiempo else set())
        for dim in mod.dimensiones.values():
            usadas |= _columnas(dim.expr)
        for med in d.medidas.values():
            if med.modelo == nm:
                usadas |= _columnas(med.expr) if med.expr else set()
                usadas |= _columnas(med.filtro) if med.filtro else set()
        faltan = sorted(usadas - cols)
        salida.append(Chequeo("esquema", f"modelo {nm}", not faltan,
                              f"faltan columnas: {', '.join(faltan)}" if faltan else f"{len(usadas)} columnas"))
    return salida


def chequear_metricas(capa: CapaSemantica, con: duckdb.DuckDBPyConnection) -> list[Chequeo]:
    salida = []
    for m in capa.definicion.metricas:
        try:
            df = capa.consultar(con, Consulta(metricas=[m], grano="mes"))
            ok = len(df) > 0 and df[m].notna().any()
            salida.append(Chequeo("métricas", m, ok, f"{len(df)} meses" if ok else "sin valores"))
        except Exception as e:  # cualquier error de compilación o ejecución se reporta, no rompe
            salida.append(Chequeo("métricas", m, False, str(e).splitlines()[0]))
    return salida


def conciliacion(capa: CapaSemantica, con: duckdb.DuckDBPyConnection, desde=None, hasta=None) -> pd.DataFrame:
    """Total de cada medida aditiva contra su suma por cada dimensión."""
    d = capa.definicion
    medidas = [m for m, x in d.medidas.items() if x.aditiva]
    simples = {x.medida: n for n, x in d.metricas.items() if x.tipo == "simple"}
    metricas = [simples[m] for m in medidas if m in simples]
    total = capa.consultar(con, Consulta(metricas=metricas, desde=desde, hasta=hasta)).iloc[0]
    filas = []
    for dim in d.dimensiones():
        df = capa.consultar(con, Consulta(metricas=metricas, dimensiones=[dim], desde=desde, hasta=hasta))
        sin_dato = df[df[dim].astype(str) == SIN_DATO]
        for m in metricas:
            suma = float(df[m].sum())
            filas.append({"dimension": dim, "metrica": m, "total": float(total[m]), "suma_segmentos": suma,
                          "diferencia": suma - float(total[m]),
                          "en_sin_dato": float(sin_dato[m].sum()) if len(sin_dato) else 0.0})
    out = pd.DataFrame(filas)
    out["ok"] = out.diferencia.abs() <= TOLERANCIA
    return out


def no_aditividad(capa: CapaSemantica, con: duckdb.DuckDBPyConnection, mes: str) -> dict:
    """Muestra por qué un conteo de distintos no se suma: días del mes vs el mes."""
    d = capa.definicion
    metricas = [n for n, x in d.metricas.items() if x.tipo == "simple" and not d.medidas[x.medida].aditiva]
    inicio = pd.Timestamp(mes)
    fin = inicio + pd.offsets.MonthEnd(0)
    salida = {}
    for m in metricas:
        diario = capa.consultar(con, Consulta(metricas=[m], grano="dia", desde=inicio.date(), hasta=fin.date()))
        mensual = capa.consultar(con, Consulta(metricas=[m], desde=inicio.date(), hasta=fin.date()))
        salida[m] = {"suma_diaria": int(diario[m].sum()), "mes": int(mensual[m].iloc[0]),
                     "promedio_diario": float(diario[m].mean())}
    return salida


def validar(capa: CapaSemantica, con: duckdb.DuckDBPyConnection) -> tuple[list[Chequeo], pd.DataFrame]:
    chequeos = chequear_esquema(capa, con)
    if not all(c.ok for c in chequeos):
        return chequeos, pd.DataFrame()
    chequeos += chequear_metricas(capa, con)
    conc = conciliacion(capa, con)
    for dim, g in conc.groupby("dimension", sort=False):
        malas = g[~g.ok]
        detalle = (", ".join(f"{r.metrica} {r.diferencia:+,.2f}" for r in malas.itertuples())
                   if len(malas) else "cuadra")
        sin = g.en_sin_dato.max()
        if len(malas) == 0 and sin > 0:
            detalle += f" (incluye '{SIN_DATO}')"
        chequeos.append(Chequeo("conciliación", dim, len(malas) == 0, detalle))
    return chequeos, conc


def huerfanos(con: duckdb.DuckDBPyConnection) -> dict:
    """Cobros cuyo comercio no está en el maestro (dato, no error de la capa)."""
    n, comercios, tpv = con.execute("""
        SELECT COUNT(*), COUNT(DISTINCT t.id_comercio),
               COALESCE(SUM(CASE WHEN t.estado = 'aprobada' THEN t.monto END), 0)
        FROM transacciones t LEFT JOIN comercios c USING (id_comercio)
        WHERE c.id_comercio IS NULL""").fetchone()
    return {"transacciones": int(n), "comercios": int(comercios), "tpv": float(tpv)}
