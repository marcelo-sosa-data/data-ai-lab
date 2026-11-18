"""
La bandeja de entrada: leer cada comprobante, validarlo y decidir a dónde va.

Leer es lo caro (Tesseract o una llamada al LLM), así que se hace una vez y
se guarda; validar y rutear es barato y se repite para probar umbrales.
Los comprobantes se procesan en el orden en que llegaron, porque el control
de duplicados depende de lo que ya se registró.
"""

from __future__ import annotations

import json
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

from .esquema import CAMPOS, Comprobante
from .reglas import Contexto, llave, registrar, validar
from .ruteo import decidir


def cargar_contexto(con: duckdb.DuckDBPyConnection) -> Contexto:
    ruc_empresa = con.execute("SELECT ruc FROM empresa").fetchone()[0]
    padron = {r["ruc"]: r for r in con.execute("SELECT * FROM padron").df().to_dict("records")}
    ordenes = {r["orden_compra"]: r for r in con.execute("SELECT * FROM ordenes_compra").df().to_dict("records")}
    return Contexto(ruc_empresa, padron, ordenes)


# ------------------------------------------------------------- lectura

_extractor = None


def _iniciar_ocr() -> None:
    global _extractor
    from .ocr import ExtractorOCR
    _extractor = ExtractorOCR()


def _leer_uno(args: tuple[int, str]) -> dict:
    doc_id, ruta = args
    t = time.perf_counter()
    lec = _extractor.extraer(Path(ruta))
    return _fila(doc_id, lec, time.perf_counter() - t)


def _fila(doc_id: int, lec, segundos: float) -> dict:
    return {"doc_id": doc_id, "extractor": lec.extractor,
            "comprobante": lec.comprobante.model_dump_json(),
            "confianza": json.dumps(lec.confianza), "texto": lec.texto, "segundos": round(segundos, 3)}


def leer_lote(recepcion: pd.DataFrame, carpeta: Path, extractor=None, procesos: int = 2,
              al_avanzar=None) -> pd.DataFrame:
    """Lee las imágenes. Sin `extractor` usa Tesseract en `procesos` procesos."""
    tareas = [(int(r.doc_id), str(carpeta / r.archivo)) for r in recepcion.itertuples()]
    filas = []
    if extractor is None:
        contexto = multiprocessing.get_context("spawn")  # fork con hilos abiertos puede colgarse
        with ProcessPoolExecutor(procesos, mp_context=contexto, initializer=_iniciar_ocr) as pool:
            for i, f in enumerate(pool.map(_leer_uno, tareas, chunksize=8), 1):
                filas.append(f)
                if al_avanzar:
                    al_avanzar(i, len(tareas))
    else:
        for i, (doc_id, ruta) in enumerate(tareas, 1):
            t = time.perf_counter()
            try:
                lec = extractor.extraer(Path(ruta))
            except Exception as e:  # una falla de la API no detiene el lote: ese va a revisión
                from .ocr import Lectura
                lec = Lectura(Comprobante(), {}, f"ERROR: {e}", getattr(extractor, "nombre", "llm"))
            filas.append(_fila(doc_id, lec, time.perf_counter() - t))
            if al_avanzar:
                al_avanzar(i, len(tareas))
    return pd.DataFrame(filas)


# ------------------------------------------------------------- ruteo

def rutear(lecturas: pd.DataFrame, recepcion: pd.DataFrame, ctx: Contexto, umbral: float,
           verdad: pd.DataFrame | None = None, usar_confianza: bool = True) -> pd.DataFrame:
    """
    Valida y decide cada comprobante en orden de llegada.

    Lo que se aprueba solo queda registrado con lo que se leyó. Lo que pasa
    por revisión queda con lo que corrige la persona (en la simulación, la
    verdad, si se pasa `verdad`) y se vuelve a validar: un IGV mal calculado
    que llegó con un campo ilegible aparece recién después de corregir.
    """
    base = recepcion.merge(lecturas, on="doc_id").sort_values(["fecha_recepcion", "doc_id"])
    corregidos = {}
    if verdad is not None:
        for f in verdad.to_dict("records"):
            corregidos[f["doc_id"]] = Comprobante(**{
                k: (None if pd.isna(f[k]) else f[k]) for k in CAMPOS if k != "fecha_emision"},
                fecha_emision=pd.Timestamp(f["fecha_emision"]).date())
    ctx.registrados, ctx.correlativos = set(), {}
    filas = []
    for r in base.itertuples():
        comp = Comprobante.model_validate_json(r.comprobante)
        conf = json.loads(r.confianza) if usar_confianza else {}
        ctx.fecha_recepcion = pd.Timestamp(r.fecha_recepcion).date()
        obs = validar(comp, ctx)
        dec = decidir(comp, conf, obs, umbral)
        tras_correccion: list[str] = []
        if dec.destino == "aprobado":
            registrar(ctx, llave(comp))
        else:
            # quien revisa corrige la lectura y los controles vuelven a correr sobre lo corregido
            corregido = corregidos.get(r.doc_id, comp)
            tras_correccion = [o.codigo for o in validar(corregido, ctx) if o.origen != "aviso"]
            registrar(ctx, llave(corregido))
        filas.append({"doc_id": r.doc_id, "destino": dec.destino, "motivos": json.dumps(dec.motivos),
                      "motivos_tras_correccion": json.dumps(tras_correccion),
                      "campos_dudosos": json.dumps(dec.campos_dudosos),
                      "observaciones": json.dumps([asdict(o) for o in obs], ensure_ascii=False)})
    return pd.DataFrame(filas)
