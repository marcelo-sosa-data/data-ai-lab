"""Escritura y lectura de resultados.duckdb, que es lo que lee el tablero."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .analisis import Lectura


def guardar(ruta: Path, tablas: dict[str, pd.DataFrame]) -> None:
    con = duckdb.connect(str(ruta))
    try:
        for nombre, df in tablas.items():
            con.register("_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM _df")
            con.unregister("_df")
    finally:
        con.close()


def leer_tabla(ruta: Path, nombre: str) -> pd.DataFrame:
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {nombre}").df()
    finally:
        con.close()


# no se para antes de una semana completa: el efecto de un lunes no es el de un sábado
DIAS_MINIMOS = 7


def _primer_dia(df: pd.DataFrame, col: str, desde: int = 1) -> int | None:
    d = df[(df[col] < 0.05) & (df.dia >= desde)]
    return int(d.dia.iloc[0]) if len(d) else None


def tablas_de_lecturas(lecturas: list[Lectura]) -> dict[str, pd.DataFrame]:
    resumen, met, gr, seg, sem, sec, srmv = [], [], [], [], [], [], []
    for lec in lecturas:
        e, p = lec.experimento, lec.lecturas[lec.experimento.primaria]
        resumen.append({
            "id_experimento": e.id, "nombre": e.nombre, "hipotesis": e.hipotesis,
            "inicio": pd.Timestamp(e.inicio), "fin": pd.Timestamp(e.fin), "primaria": e.primaria,
            "n_control": lec.n_control, "n_tratamiento": lec.n_tratamiento, "p_srm": lec.p_srm,
            "relativo": p.relativo, "relativo_bajo": p.relativo_bajo, "relativo_alto": p.relativo_alto,
            "p_valor": p.p_valor, "reduccion_varianza": p.reduccion_varianza,
            "veredicto": lec.decision.veredicto, "motivo": lec.decision.motivo,
            "dia_parada_msprt": _primer_dia(lec.secuencial, "p_siempre_valido", DIAS_MINIMOS),
            "dia_primer_p05": _primer_dia(lec.secuencial, "p_clasico"),
        })
        met.append(lec.metricas.assign(id_experimento=e.id))
        gr.append(pd.DataFrame([vars(g) for g in lec.decision.guardrails]
                               or [{"metrica": None, "margen": None, "estado": None, "peor_caso": None}])
                  .assign(id_experimento=e.id).dropna(subset=["metrica"]))
        seg.append(lec.segmentos.assign(id_experimento=e.id))
        sem.append(lec.semanas.assign(id_experimento=e.id))
        sec.append(lec.secuencial.assign(id_experimento=e.id))
        srmv.append(lec.srm_por_version.assign(id_experimento=e.id))
    return {
        "resumen": pd.DataFrame(resumen), "metricas": pd.concat(met, ignore_index=True),
        "guardrails": pd.concat(gr, ignore_index=True), "segmentos": pd.concat(seg, ignore_index=True),
        "semanas": pd.concat(sem, ignore_index=True), "secuencial": pd.concat(sec, ignore_index=True),
        "srm_version": pd.concat(srmv, ignore_index=True),
    }
