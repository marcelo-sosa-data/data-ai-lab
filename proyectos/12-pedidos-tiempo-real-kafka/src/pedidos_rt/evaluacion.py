"""Compara el tablero de 15 minutos con el flujo en streaming.

Para cada forma de vigilar (variante) se mide, contra los incidentes
sembrados en el generador: cuántos detecta, cuánto tarda desde que empezó
el problema, cuántas alertas no corresponden a ningún incidente y cuántos
pedidos entraron a la zona antes de que alguien se enterara.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd

from . import as_is
from .config import Ajustes

HOLGURA_EMPAREJAR_MIN = 20     # una alerta cuenta para el incidente hasta 20 min después del fin


def leer_carpeta(directorio: Path) -> pd.DataFrame:
    archivos = sorted(Path(directorio).glob("*.parquet"))
    if not archivos:
        return pd.DataFrame()
    return duckdb.sql(f"SELECT * FROM read_parquet({[a.as_posix() for a in archivos]})").df()


def a_ts(ms) -> pd.Timestamp:
    return pd.Timestamp(int(ms), unit="ms")


def emparejar(alertas: pd.DataFrame, incidentes: pd.DataFrame, pedidos: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Primera apertura de alerta de cada incidente y alertas sin incidente."""
    aperturas = alertas[alertas["accion"] == "abrir"].copy() if len(alertas) else alertas
    if len(aperturas):
        aperturas["ts"] = pd.to_datetime(aperturas["detectado_ms"], unit="ms")
    usadas = set()
    filas = []
    for inc in incidentes.itertuples(index=False):
        tope = inc.fin + pd.Timedelta(minutes=HOLGURA_EMPAREJAR_MIN)
        cand = aperturas[(aperturas["zona"] == inc.zona) & (aperturas["ts"] >= inc.inicio)
                         & (aperturas["ts"] <= tope)] if len(aperturas) else aperturas
        usadas.update(cand.index)
        detectado = cand["ts"].min() if len(cand) else pd.NaT
        hasta = detectado if pd.notna(detectado) else inc.fin
        p = pedidos[(pedidos["zona"] == inc.zona) & (pedidos["ev_creado"] >= inc.inicio)
                    & (pedidos["ev_creado"] < hasta)]
        filas.append({
            "incidente": inc.incidente, "zona": inc.zona, "inicio": inc.inicio, "fin": inc.fin,
            "causa": inc.causa, "detectado": detectado,
            "demora_min": (detectado - inc.inicio).total_seconds() / 60 if pd.notna(detectado) else None,
            "pedidos_antes_alerta": len(p),
            "cancelados_antes_alerta": int(p["cancelado"].sum()),
        })
    falsas = len(aperturas) - len(usadas) if len(aperturas) else 0
    return pd.DataFrame(filas), falsas


def resumir(nombre: str, det: pd.DataFrame, falsas: int, dias: int) -> dict:
    d = det["demora_min"].dropna()
    return {
        "variante": nombre,
        "detectados": int(det["detectado"].notna().sum()),
        "incidentes": len(det),
        "demora_mediana_min": round(float(d.median()), 1) if len(d) else None,
        "demora_max_min": round(float(d.max()), 1) if len(d) else None,
        "falsas_alarmas": falsas,
        "falsas_por_dia": round(falsas / dias, 2),
        "pedidos_antes_alerta": int(det["pedidos_antes_alerta"].sum()),
        "cancelados_antes_alerta": int(det["cancelados_antes_alerta"].sum()),
    }


def consistencia_flujo(minutos: pd.DataFrame, tardios: pd.DataFrame, con) -> dict:
    """Creados y asignados del flujo, con y sin la conciliación de tardíos, contra la verdad."""
    verdad = dict(con.execute(
        "SELECT tipo, count(*) FROM eventos WHERE NOT es_reintento GROUP BY ALL").fetchall())
    salida = {}
    for tipo, col in (("creado", "creados"), ("asignado", "asignados")):
        vivo = int(minutos[col].sum())
        tard = int((tardios["tipo"] == tipo).sum()) if len(tardios) else 0
        salida[tipo] = {"verdad": int(verdad[tipo]), "en_vivo": vivo, "tardios": tard,
                        "conciliado": vivo + tard}
    return salida


def correr_flujo(aj: Ajustes, gracia_s: int, base: Path, publicar: bool) -> Path:
    """Procesa el tópico completo con una gracia dada, en un grupo y carpeta propios."""
    from .procesador import correr  # importa Quix solo si hace falta

    salida = base / f"gracia_{gracia_s:03d}s"
    # grupo nuevo en cada corrida: siempre lee el tópico desde el principio
    grupo = f"evaluacion-gracia-{gracia_s}-{uuid.uuid4().hex[:6]}"
    shutil.rmtree(salida, ignore_errors=True)
    shutil.rmtree(aj.dir_estado / grupo, ignore_errors=True)
    correr(replace(aj, gracia_ms=gracia_s * 1000), grupo, salida, publicar=publicar, espera_s=8)
    shutil.rmtree(aj.dir_estado / grupo, ignore_errors=True)
    return salida


def evaluar(aj: Ajustes, dir_datos: Path, gracias=(0, 30, 60, 120, 300), principal: int = 60,
            procesar: bool = True) -> dict:
    """Corre todas las variantes y guarda resultados.duckdb. Devuelve el resumen."""
    regla = aj.regla
    con = as_is.conectar(dir_datos / "eventos.parquet")
    incidentes = pd.read_parquet(dir_datos / "incidentes.parquet")
    pedidos = con.execute("""
        SELECT pedido_id, zona, ev_creado,
               EXISTS (SELECT 1 FROM eventos e WHERE e.pedido_id = p.pedido_id
                       AND e.tipo = 'cancelado') AS cancelado
        FROM pedidos p
    """).df()
    dias = int(con.execute("SELECT count(DISTINCT date_trunc('day', ts_evento)) FROM eventos WHERE tipo = 'creado'").fetchone()[0])

    resumen, detalle, alertas_todas = [], [], []

    def registrar(nombre, alertas):
        det, falsas = emparejar(alertas, incidentes, pedidos)
        resumen.append(resumir(nombre, det, falsas, dias))
        detalle.append(det.assign(variante=nombre))
        if len(alertas):
            alertas_todas.append(alertas.assign(variante=nombre))

    tab = as_is.tablero_demoradas(con, regla, 15)
    registrar("Tablero cada 15 min, % demoradas (AS IS)",
              as_is.alertas_de_serie(tab, "en_rojo", regla, por_evaluacion=True))
    for cada in (15, 5):
        cola = as_is.cola_por_corte(con, regla, cada, con_llegada=True)
        registrar(f"Batch cada {cada} min, cola sin motorizado",
                  as_is.alertas_de_serie(cola, None, regla, por_evaluacion=True))

    base = aj.dir_salida
    consistencia = {}
    for g in gracias:
        carpeta = base / f"gracia_{g:03d}s"
        if procesar:
            carpeta = correr_flujo(aj, g, base, publicar=(g == principal))
        minutos = leer_carpeta(carpeta / "minutos")
        alertas = leer_carpeta(carpeta / "alertas")
        tardios = leer_carpeta(carpeta / "tardios")
        if g == principal:
            # la alerta lee la cola al momento y no depende de la gracia
            registrar("Streaming, cola al minuto (TO BE)", alertas)
        c = consistencia_flujo(minutos, tardios, con)
        retraso = ((minutos["emitido_ms"] - minutos["fin_ms"]) / 1000) if len(minutos) else pd.Series(dtype=float)
        consistencia[g] = {
            **{f"{t}_{k}": v for t, d in c.items() for k, v in d.items()},
            "tardios_total": len(tardios),
            "retraso_mediano_s": round(float(retraso.median()), 1) if len(retraso) else None,
            "retraso_p90_s": round(float(retraso.quantile(0.9)), 1) if len(retraso) else None,
        }

    ref = as_is.cola_por_corte(con, regla, 1, con_llegada=False)
    registrar("Referencia: cola con datos completos al minuto",
              as_is.alertas_de_serie(ref, None, regla, por_evaluacion=False))

    tablero = as_is.cifras_tablero(con, 15)
    res = {
        "resumen": pd.DataFrame(resumen),
        "detalle": pd.concat(detalle, ignore_index=True),
        "alertas": pd.concat(alertas_todas, ignore_index=True) if alertas_todas else pd.DataFrame(),
        "consistencia_flujo": pd.DataFrame(consistencia).T.reset_index(names="gracia_s"),
        "consistencia_tablero": pd.DataFrame(tablero).T.reset_index(names="tipo"),
        "tablero": tab,
    }
    guardar(res, dir_datos / "resultados.duckdb")
    return res


def guardar(res: dict, ruta: Path) -> None:
    ruta.unlink(missing_ok=True)
    with duckdb.connect(str(ruta)) as con:
        for nombre, df in res.items():
            if len(df):
                con.register("tmp", df)
                con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM tmp")
                con.unregister("tmp")
