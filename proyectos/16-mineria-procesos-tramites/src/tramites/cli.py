"""
Uso:
    python -m tramites generar [--escala 0.2]   # exports sintéticos del sistema de trámites
    python -m tramites analizar                 # proceso real: variantes, DFG, conformidad, tiempos por área
    python -m tramites simular [--replicas 30]  # estima con ene-jun, valida en jul-oct y corre los escenarios
    python -m tramites verdad                   # el generador corre cada escenario: cuánto se equivoca la simulación
    python -m tramites todo                     # todo lo anterior (genera si falta)
    python -m tramites resumen                  # vuelve a mostrar los resultados guardados
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from . import catalogos as K
from . import conformidad as C
from . import descubrimiento as D
from . import evaluacion as E
from . import resultados as Res
from . import simulacion as S
from . import tiempos as T
from .lectura import leer

RAIZ = Path(__file__).parents[2]
DATOS = Path(os.getenv("TRAMITES_DATOS", RAIZ / "datos"))
EXPORTS = DATOS / "exports"
RESULTADOS = DATOS / "resultados.duckdb"

consola = Console()
CIAN = "#22D3EE"
CORTO = {K.CONVALIDACION: "Convalidación", K.RETIRO: "Retiro"}


def _tabla(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", title_style=f"bold {CIAN}", header_style="dim",
                 box=None, padding=(0, 2))


def _pct(v) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:.1%}"


def _num(v, d=1) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:,.{d}f}"


def cmd_generar(a) -> int:
    sys.path.insert(0, str(RAIZ / "datos"))
    from generar_datos import generar
    t = time.time()
    generar(DATOS, escala=a.escala, seed=a.seed)
    consola.print(f"Exports en {EXPORTS} ({time.time() - t:.1f} s)")
    return 0


def cmd_analizar(a) -> int:
    t = time.time()
    log = leer(EXPORTS)
    ev_t = T.tiempos_evento(log.eventos)
    casos = T.casos(log)
    al = C.alinear(log.eventos, log.tramites)
    ctrl = C.controles(log.eventos, log.tramites)
    casos = casos.merge(al[["id_tramite", "fitness", "sobra", "falta"]], on="id_tramite", how="left")
    casos = casos.merge(ctrl.drop(columns="tipo"), on="id_tramite", how="left")
    arcos = pd.concat([D.dfg(log.eventos[log.eventos["id_tramite"].isin(
        log.tramites.loc[log.tramites["tipo"] == tipo, "id_tramite"])]).assign(tipo=tipo)
        for tipo in (K.CONVALIDACION, K.RETIRO)], ignore_index=True)
    variantes = D.variantes(log.eventos, casos)
    area = T.por_area(ev_t, log.tramites)
    reparto = T.reparto_tiempo(ev_t, log.tramites)
    aus = S.ausencias_direccion(ev_t, log.tramites)
    perdido = T.trabajo_perdido(ev_t, log.tramites)
    res_casos = T.resumen_casos(casos)
    res_ctrl = C.resumen_controles(ctrl)
    conforme = al.groupby("tipo")["fitness"].agg(conformes=lambda s: (s == 1).mean(), media="mean").reset_index()

    eventos = ev_t.merge(log.tramites[["id_tramite", "tipo", "carrera"]], on="id_tramite")
    Res.guardar(RESULTADOS, {
        "casos": casos, "eventos": eventos.drop(columns=["fin_anterior"]), "arcos": arcos,
        "variantes": variantes, "por_area": area, "reparto": reparto, "ausencias": aus,
        "resumen_casos": res_casos, "controles": res_ctrl, "conformidad": conforme,
    }, meta={"lectura": log.hallazgos, "trabajo_perdido": perdido,
             "rango_log": [str(log.tramites["registro"].min()), str(log.eventos["fin"].max())]})

    h = log.hallazgos
    consola.print(f"Log: {h['eventos']:,} eventos de {len(log.tramites):,} trámites; "
                  f"{h['duplicados']} duplicados quitados, {h['abiertos']} abiertos al corte")
    mostrar_analisis(res_casos, area, res_ctrl, conforme, variantes, perdido, aus)
    consola.print(f"[dim]{time.time() - t:.1f} s · {RESULTADOS}[/]")
    return 0


def mostrar_analisis(res_casos, area, res_ctrl, conforme, variantes, perdido, aus) -> None:
    t = _tabla("Trámites de ene a nov 2026")
    for c in ["Tipo", "Trámites", "Mediana días", "p90 días", "Fuera de plazo", "Con reproceso", "Excepción"]:
        t.add_column(c, justify="right" if c != "Tipo" else "left")
    for r in res_casos.itertuples():
        t.add_row(CORTO[r.tipo], f"{r.tramites:,}", _num(r.mediana_dias), _num(r.p90_dias),
                  _pct(r.pct_fuera_plazo), _pct(r.pct_reproceso), _pct(r.pct_excepcion))
    consola.print(t)

    t = _tabla("Lo que reporta cada área contra lo que el trámite pasa en ella (horas hábiles)")
    for c in ["Tipo", "Área", "Atención media", "En el área", "% del tiempo"]:
        t.add_column(c, justify="right" if c not in ("Tipo", "Área") else "left")
    for r in area.sort_values(["tipo", "pct_del_tiempo"], ascending=[True, False]).itertuples():
        t.add_row(CORTO[r.tipo], r.area, _num(r.atencion_media_h), _num(r.en_area_media_h),
                  _pct(r.pct_del_tiempo))
    consola.print(t)

    t = _tabla("Conformidad con el reglamento")
    t.add_column("Tipo"), t.add_column("Trazas conformes", justify="right")
    for r in conforme.itertuples():
        t.add_row(CORTO[r.tipo], _pct(r.conformes))
    consola.print(t)
    t = _tabla("Controles")
    for c in ["Control", "Evaluados", "Casos", "%"]:
        t.add_column(c, justify="right" if c != "Control" else "left")
    for r in res_ctrl.itertuples():
        t.add_row(r.control, f"{r.evaluados:,}", f"{r.casos:,}", _pct(r.pct))
    consola.print(t)

    for tipo in (K.CONVALIDACION, K.RETIRO):
        v = variantes[variantes["tipo"] == tipo]
        consola.print(f"[{CIAN}]{CORTO[tipo]}[/]: {len(v)} variantes; las 3 primeras cubren "
                      f"{v.head(3)['pct'].sum():.1%}")
    consola.print(f"Convalidaciones archivadas: {perdido['archivados']} "
                  f"({perdido['archivados_con_evaluacion']} ya evaluadas, {perdido['archivados_con_firma']} "
                  f"con resolución firmada), {perdido['horas_direccion']:.0f} h de Dirección")
    if len(aus):
        consola.print(f"Ausencias de Dirección detectadas: {len(aus)} carreras, "
                      f"{aus['desde'].min()} a {aus['hasta'].max()}")


def cmd_simular(a) -> int:
    t = time.time()
    log = leer(EXPORTS)
    ev_t = T.tiempos_evento(log.eventos)
    casos = T.casos(log)
    par = S.estimar(ev_t, log.tramites, K.INICIO_LOG, K.INICIO_PRUEBA)
    prueba = E.periodo_prueba(log.tramites)
    obs = E.observado(casos[casos["id_tramite"].isin(prueba["id_tramite"])])
    ind, extras = E.correr_escenarios(par, prueba, replicas=a.replicas)
    res = E.comparar(ind, obs)
    val = E.validacion(res, obs)
    params = pd.DataFrame([{"parametro": k, "valor": v} for k, v in par.p.items()])
    Res.guardar(RESULTADOS, {"escenarios": res, "escenarios_replicas": ind, "escenarios_extras": extras,
                             "validacion": val, "observado_prueba": obs, "parametros": params},
                meta={"firma": {"dias": list(par.firma_dias), "hora": par.firma_hora,
                                "salto": par.firma_salto},
                      "replicas": a.replicas, "prueba_tramites": len(prueba)})
    mostrar_simulacion(val, res, extras)
    consola.print(f"[dim]{time.time() - t:.1f} s · {len(prueba):,} trámites de jul-oct · "
                  f"{a.replicas} réplicas[/]")
    return 0


def mostrar_simulacion(val, res, extras) -> None:
    nombres = {"mediana_dias": "Mediana (días)", "p90_dias": "p90 (días)",
               "pct_fuera_plazo": "Fuera de plazo", "pct_excepcion": "Con excepción"}
    t = _tabla("Validación: proceso actual simulado con ene-jun contra lo observado en jul-oct")
    for c in ["Tipo", "Indicador", "Observado", "Simulado", "Rango 5-95%", "Error"]:
        t.add_column(c, justify="right" if c not in ("Tipo", "Indicador") else "left")
    for r in val.itertuples():
        f = _pct if r.metrica.startswith("pct") else _num
        t.add_row(CORTO[r.tipo], nombres[r.metrica], f(r.observado), f(r.simulado),
                  f"{f(r.p05)} a {f(r.p95)}", f"{r.error_relativo:+.1%}")
    consola.print(t)

    t = _tabla("Escenarios: lo observado por el cambio relativo que da la simulación")
    for c in ["Escenario", "Tipo", "Mediana", "p90", "Fuera de plazo", "Excepción"]:
        t.add_column(c, justify="right" if c not in ("Escenario", "Tipo") else "left")
    for r in res.itertuples():
        t.add_row(r.nombre, CORTO[r.tipo], _num(r.estimado_mediana_dias), _num(r.estimado_p90_dias),
                  _pct(r.estimado_pct_fuera_plazo), _pct(r.estimado_pct_excepcion))
    consola.print(t)
    t = _tabla("Carga de trabajo por escenario")
    for c in ["Escenario", "Revisiones Sec./conv.", "Evaluaciones/conv.", "Evaluadas y archivadas",
              "Retiros por Dirección"]:
        t.add_column(c, justify="right" if c != "Escenario" else "left")
    for r in extras.itertuples():
        t.add_row(r.nombre, _num(r.revisiones_secretaria_por_conv, 2), _num(r.evaluaciones_por_conv, 2),
                  _num(r.evaluaciones_en_archivados, 1), _pct(r.pct_retiros_por_direccion))
    consola.print(t)


def cmd_verdad(a) -> int:
    t = time.time()
    if "escenarios" not in Res.tablas(RESULTADOS):
        consola.print("Primero corre: python -m tramites simular")
        return 1
    casos_v = pd.read_parquet(DATOS / "verdad" / "casos.parquet")
    log = leer(EXPORTS)
    ids = E.periodo_prueba(log.tramites)["id_tramite"]
    ver = E.verdad(casos_v, ids, RAIZ)
    cmp = E.contra_verdad(Res.leer(RESULTADOS, "escenarios"), ver)
    Res.guardar(RESULTADOS, {"verdad": ver, "contra_verdad": cmp})
    mostrar_verdad(cmp)
    consola.print(f"[dim]{time.time() - t:.1f} s[/]")
    return 0


def mostrar_verdad(cmp) -> None:
    nombres = {"mediana_dias": "Mediana", "p90_dias": "p90", "pct_fuera_plazo": "Fuera de plazo",
               "pct_excepcion": "Excepción"}
    t = _tabla("Efecto de cada escenario: simulación contra generador")
    for c in ["Escenario", "Tipo", "Indicador", "Estimado", "Real", "Efecto estimado", "Efecto real"]:
        t.add_column(c, justify="right" if c not in ("Escenario", "Tipo", "Indicador") else "left")
    for r in cmp[cmp["escenario"] != "actual"].itertuples():
        pct = r.metrica.startswith("pct")
        f = _pct if pct else _num
        d = (lambda v: f"{v * 100:+.1f} pp") if pct else (lambda v: f"{v:+.1f}")
        t.add_row(K.ESCENARIOS[r.escenario][0], CORTO[r.tipo], nombres[r.metrica], f(r.estimado),
                  f(r.real), d(r.efecto_estimado), d(r.efecto_real))
    consola.print(t)


def cmd_todo(a) -> int:
    if not (EXPORTS / "log_tramites.csv").exists():
        cmd_generar(a)
    return cmd_analizar(a) or cmd_simular(a) or cmd_verdad(a)


def cmd_resumen(a) -> int:
    if not RESULTADOS.exists():
        consola.print("No hay resultados. Corre: python -m tramites todo")
        return 1
    tb = Res.tablas(RESULTADOS)
    m = Res.meta(RESULTADOS)
    if "casos" in tb:
        mostrar_analisis(Res.leer(RESULTADOS, "resumen_casos"), Res.leer(RESULTADOS, "por_area"),
                         Res.leer(RESULTADOS, "controles"), Res.leer(RESULTADOS, "conformidad"),
                         Res.leer(RESULTADOS, "variantes"), m.get("trabajo_perdido", {}),
                         Res.leer(RESULTADOS, "ausencias"))
    if "escenarios" in tb:
        mostrar_simulacion(Res.leer(RESULTADOS, "validacion"), Res.leer(RESULTADOS, "escenarios"),
                           Res.leer(RESULTADOS, "escenarios_extras"))
    if "contra_verdad" in tb:
        mostrar_verdad(Res.leer(RESULTADOS, "contra_verdad"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tramites", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--escala", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=16)
    sub.add_parser("analizar")
    s = sub.add_parser("simular")
    s.add_argument("--replicas", type=int, default=30)
    sub.add_parser("verdad")
    t = sub.add_parser("todo")
    t.add_argument("--escala", type=float, default=1.0)
    t.add_argument("--seed", type=int, default=16)
    t.add_argument("--replicas", type=int, default=30)
    sub.add_parser("resumen")
    a = ap.parse_args(argv)
    return {"generar": cmd_generar, "analizar": cmd_analizar, "simular": cmd_simular,
            "verdad": cmd_verdad, "todo": cmd_todo, "resumen": cmd_resumen}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
