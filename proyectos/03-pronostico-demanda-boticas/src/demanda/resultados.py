"""
Guarda y lee los resultados en una base DuckDB aparte (datos/resultados.duckdb),
para que la app y los reportes no tengan que reentrenar nada.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .backtest import Backtest
from .intervalos import Calibrador


def guardar(ruta: Path, tablas: dict[str, pd.DataFrame]) -> None:
    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in tablas.items():
            con.register("df_tmp", df)
            con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM df_tmp")
            con.unregister("df_tmp")
    finally:
        con.close()


def leer(ruta: Path, sql: str, params: list | None = None) -> pd.DataFrame:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}. Corre primero: python -m demanda backtest")
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def _cal_a_filas(cal: Calibrador, corte, tipo: str) -> list[dict]:
    return [{"corte": corte, "tipo": tipo, "segmento": seg, "nivel": q, "valor": v}
            for seg, qs in cal.cuantiles.items() for q, v in qs.items()]


def _filas_a_cal(df: pd.DataFrame) -> Calibrador:
    cuantiles: dict[str, dict[float, float]] = {}
    for r in df.itertuples():
        cuantiles.setdefault(r.segmento, {})[float(r.nivel)] = float(r.valor)
    return Calibrador(cuantiles, tuple(sorted(df.nivel.unique())))


def guardar_backtest(ruta: Path, bt: Backtest, vigentes: tuple[Calibrador, Calibrador]) -> None:
    filas = []
    for c, cal in bt.calibradores.items():
        filas += _cal_a_filas(cal, c, "diario")
    for c, cal in bt.calibradores_suma.items():
        filas += _cal_a_filas(cal, c, "pedido")
    filas += _cal_a_filas(vigentes[0], None, "diario")
    filas += _cal_a_filas(vigentes[1], None, "pedido")
    p = bt.predicciones.copy()
    for c in ("categoria", "region", "segmento"):
        p[c] = p[c].astype(str)
    tablas = {"predicciones": p, "cortes": pd.DataFrame({"corte": bt.cortes}),
              "calibracion": pd.DataFrame(filas)}
    if bt.importancia is not None:
        tablas["importancia"] = bt.importancia
    guardar(ruta, tablas)


def cargar_backtest(ruta: Path) -> tuple[Backtest, tuple[Calibrador, Calibrador]]:
    p = leer(ruta, "SELECT * FROM predicciones")
    cortes = list(pd.to_datetime(leer(ruta, "SELECT corte FROM cortes ORDER BY corte").corte))
    cal = leer(ruta, "SELECT * FROM calibracion")
    bt = Backtest(p, cortes)
    for (c, tipo), g in cal[cal.corte.notna()].groupby(["corte", "tipo"]):
        destino = bt.calibradores if tipo == "diario" else bt.calibradores_suma
        destino[pd.Timestamp(c)] = _filas_a_cal(g)
    vig = cal[cal.corte.isna()]
    vigentes = (_filas_a_cal(vig[vig.tipo == "diario"]), _filas_a_cal(vig[vig.tipo == "pedido"]))
    return bt, vigentes
