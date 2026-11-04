"""
Genera el CDC de la tabla `envios` de "Kallpa Envíos", un courier ficticio de última milla
para tiendas online en Lima, Callao y siete ciudades de provincia.

Primero se simula la vida de cada envío en la base transaccional (registrado, recogido,
en almacén, en ruta, entregado, intento fallido, devuelto o cancelado) y cada cambio queda
como un evento con el formato de Debezium: `lsn`, `op` (c/u/d), `ts_ms`, imagen `antes` y
`despues`. Después se simula el conector que deja esos eventos en archivos cada 6 horas:
ahí aparecen los eventos tardíos y los duplicados.

Patrones que trae:
  - más envíos los lunes (lo comprado el fin de semana), pocos los domingos y feriados
  - campaña de ofertas del 14 al 16 de julio: los registros se duplican y el reparto no da
    abasto, sube la proporción de envíos entregados después de la fecha prometida
  - el motorizado confirma la entrega desde el celular; sin señal, la confirmación se
    sincroniza horas después (más en la periferia y en provincia): `entregado_en` es la hora
    real, el commit llega después
  - más intentos fallidos en la periferia y en envíos contra entrega
  - envíos de prueba del cliente QA que Operaciones borra cada lunes (eventos `d`)
  - el 15 de setiembre se agrega la columna `franja_horaria` en la base de origen
  - incidentes de datos con fecha conocida:
      * 18 al 20 de agosto: la app de agencias manda el peso en gramos; el 21 un script lo
        corrige en origen
      * 6 de octubre, 10:00 a 15:59: un deploy manda los estados en mayúsculas; a las 18:30
        se normalizan en origen
      * distritos mal escritos ("Surco", "SJL", "Miraflores ") en algunos envíos
  - del conector: ~1.6% de eventos llegan uno o más lotes tarde, ~0.2% llegan duplicados y
    tres reinicios reenvían las últimas dos horas del lote anterior

Salida:
  datos/cdc/lote=AAAA-MM-DDTHH/parte-N.jsonl.gz    eventos tal como los deja el conector
  datos/origen/envios.parquet                      estado final de la tabla en origen
  datos/origen/manifiesto.json                     qué se inyectó (para validar, no lo lee el pipeline)

Uso:
    python datos/generar_datos.py                      # jul-oct 2026, ~140 mil envíos
    python datos/generar_datos.py --escala 0.1 --desde 2026-08-15 --hasta 2026-08-24
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from lakehouse.calendario import es_habil, lote_de, lote_siguiente, siguiente_habil  # noqa: E402

DIR_DEFECTO = Path(__file__).parent
INICIO, FIN = date(2026, 7, 1), date(2026, 10, 31)

ZONAS = {  # peso en la demanda, fallo al primer intento, prob. de entregar sin señal, rango de couriers
    "lima_centro": dict(peso=0.38, fallo=0.05, sin_senal=0.03, couriers=(101, 160)),
    "lima_periferia": dict(peso=0.34, fallo=0.10, sin_senal=0.10, couriers=(201, 270)),
    "callao": dict(peso=0.10, fallo=0.08, sin_senal=0.06, couriers=(301, 320)),
    "provincia": dict(peso=0.18, fallo=0.08, sin_senal=0.18, couriers=(401, 440)),
}
DIA_SEMANA = [1.25, 1.10, 1.00, 1.00, 0.95, 0.70, 0.45]
CAMPANIA = {date(2026, 7, 14): 2.4, date(2026, 7, 15): 2.3, date(2026, 7, 16): 2.1, date(2026, 7, 17): 1.3}
DIAS_SATURADOS = {date(2026, 7, d) for d in range(15, 21)}
ENVIOS_DIA = 1050
CLIENTE_QA = 9001

GRAMOS = (datetime(2026, 8, 18, 10), datetime(2026, 8, 20, 16), datetime(2026, 8, 21, 11, 0))
MAYUSCULAS = (datetime(2026, 10, 6, 10), datetime(2026, 10, 6, 16), datetime(2026, 10, 6, 18, 30))
ALTER_FRANJA = datetime(2026, 9, 15, 8, 0)
REINICIOS = ["2026-07-09T12", "2026-08-19T18", "2026-10-21T06"]
ERRATAS = {"Santiago de Surco": "Surco", "San Juan de Lurigancho": "SJL",
           "San Martín de Porres": "San Martin de Porres", "Miraflores": "Miraflores "}
P_ERRATA = 0.004  # sobre los envíos de esos cuatro distritos


def _h(d: date, horas: float) -> datetime:
    return datetime.combine(d, datetime.min.time()) + timedelta(hours=float(horas))


def _ts(x: datetime | None) -> str | None:
    return None if x is None else x.strftime("%Y-%m-%d %H:%M:%S")


class Simulador:
    def __init__(self, escala: float, seed: int, desde: date, hasta: date):
        self.rng = np.random.default_rng(seed)
        self.escala, self.desde, self.hasta = escala, desde, hasta
        self.fin = _h(hasta + timedelta(days=1), 0)  # nada se commitea después del último corte
        ref = pd.read_csv(RAIZ / "referencia" / "distritos.csv")
        self.distritos = {z: list(g["distrito"]) for z, g in ref.groupby("zona")}
        self.zona_de = dict(zip(ref["distrito"], ref["zona"]))
        n_clientes = 320
        self.clientes = np.arange(1001, 1001 + n_clientes)
        self.p_cliente = self.rng.pareto(1.3, n_clientes) + 0.2
        self.p_cliente /= self.p_cliente.sum()
        self.canal_cliente = self.rng.choice(["api", "panel_web", "agencia"], n_clientes, p=[0.45, 0.30, 0.25])
        self.eventos: list[dict] = []
        self.manifiesto = defaultdict(list)

    # ------------------------------------------------------------ vida de un envío

    def _hora_registro(self) -> float:
        h = self.rng.choice(np.arange(24), p=_PERFIL_HORA)
        return h + self.rng.random()

    def _envio(self, id_envio: int, d: date) -> None:
        r = self.rng
        qa = r.random() < 3 / ENVIOS_DIA
        zona = r.choice(list(ZONAS), p=[z["peso"] for z in ZONAS.values()])
        distrito = r.choice(self.distritos[zona])
        ic = r.choice(len(self.clientes), p=self.p_cliente)
        cliente, canal = int(self.clientes[ic]), str(self.canal_cliente[ic])
        if qa:
            cliente, canal = CLIENTE_QA, "api"
        t_reg = _h(d, self._hora_registro())
        habil = es_habil(d)
        if zona == "provincia":
            servicio = r.choice(["express", "estandar"], p=[0.3, 0.7])
        else:
            servicio = r.choice(["mismo_dia", "express", "estandar"], p=[0.12, 0.38, 0.50])
            if servicio == "mismo_dia" and (not habil or t_reg.hour >= 13):
                servicio = "express"
        corte_dia = habil and t_reg.hour < 15  # lo registrado después de las 15:00 cuenta desde el día siguiente
        base = d if corte_dia else siguiente_habil(d, 1)
        dias = {"mismo_dia": 0, "express": 1 if zona != "provincia" else 2,
                "estandar": 2 if zona != "provincia" else 3}[servicio]
        promesa = base if dias == 0 else siguiente_habil(base, dias)
        cod = r.random() < 0.30
        franja = r.choice(["manana", "tarde", "noche"], p=[0.45, 0.40, 0.15]) if t_reg >= ALTER_FRANJA else None
        fila = {
            "id_envio": id_envio, "codigo_seguimiento": f"KL{2607000000 + id_envio:010d}",
            "id_cliente": cliente, "canal": canal, "servicio": servicio, "distrito": distrito,
            "peso_kg": round(float(np.clip(r.lognormal(0.3, 0.8), 0.05, 30)), 2),
            "monto_cod": round(float(r.lognormal(4.2, 0.6)), 1) if cod else 0.0,
            "estado": "registrado", "intentos": 0, "id_courier": None,
            "registrado_en": _ts(t_reg), "fecha_promesa": promesa.isoformat(),
            "entregado_en": None, "actualizado_en": _ts(t_reg), "franja_horaria": franja,
        }
        if distrito in ERRATAS and r.random() < P_ERRATA and not qa:
            fila["distrito"] = ERRATAS[distrito]
            self.manifiesto["erratas_distrito"].append(id_envio)

        pasos: list[tuple[datetime, dict]] = [(t_reg, dict(fila))]

        def cambio(t: datetime, **campos) -> None:
            t = max(t, pasos[-1][0] + timedelta(seconds=int(r.integers(5, 90))))
            fila.update(campos, actualizado_en=_ts(t))
            pasos.append((t, dict(fila)))

        if qa or r.random() < 0.025:
            cambio(t_reg + timedelta(hours=r.uniform(0.5, 20)), estado="cancelado")
            self._emitir(pasos, qa=qa)
            return

        # reprogramación pedida por el cliente: cambia la promesa, no el estado
        if servicio != "mismo_dia" and zona != "provincia" and r.random() < 0.02:
            promesa = siguiente_habil(promesa, int(r.integers(1, 3)))
            cambio(t_reg + timedelta(hours=r.uniform(1, 6)), fecha_promesa=promesa.isoformat())

        if servicio == "mismo_dia":
            t_rec = t_reg + timedelta(hours=r.uniform(0.5, 1.5))
        else:
            t_rec = t_reg + timedelta(hours=r.uniform(1, 4))
            if not corte_dia or t_rec.hour >= 20:
                t_rec = _h(base, r.uniform(9, 11.5))
        cambio(t_rec, estado="recogido")
        t_alm = t_rec + timedelta(hours=r.uniform(1, 3))
        cambio(t_alm, estado="en_almacen")

        if servicio == "mismo_dia":
            dia_ruta = t_alm.date()
            inicio_ruta = max(t_alm + timedelta(minutes=30), _h(dia_ruta, r.uniform(13.5, 15)))
        else:
            temprano = siguiente_habil(t_alm.date(), 1)
            dia_ruta = temprano if (r.random() < 0.45 or temprano >= promesa) else promesa
            p_atraso = 0.35 if (dia_ruta in DIAS_SATURADOS and zona != "provincia") else 0.04
            if dia_ruta.weekday() == 5:
                p_atraso += 0.04
            if r.random() < p_atraso:
                dia_ruta = siguiente_habil(dia_ruta, 1)
            inicio_ruta = _h(dia_ruta, r.uniform(7.5, 9.5))

        z = ZONAS[zona]
        p_fallo = z["fallo"] + (0.06 if cod else 0.0)
        courier = int(r.integers(*z["couriers"]))
        for intento in range(1, 4):
            cambio(inicio_ruta, estado="en_ruta", id_courier=courier)
            if franja:
                ventana = {"manana": (9, 12), "tarde": (12, 17), "noche": (17, 21)}[franja]
                t_int = _h(inicio_ruta.date(), r.uniform(*ventana))
            else:
                t_int = inicio_ruta + timedelta(hours=r.uniform(0.5, 10))
            t_int = min(max(t_int, inicio_ruta + timedelta(minutes=20)), _h(inicio_ruta.date(), 21))
            # sin señal, la app del motorizado sincroniza después
            if r.random() < z["sin_senal"]:
                demora = timedelta(hours=float(np.clip(r.lognormal(1.1, 0.9), 0.3, 30)))
            else:
                demora = timedelta(seconds=int(r.integers(5, 240)))
            if r.random() >= p_fallo:
                cambio(t_int + demora, estado="entregado", intentos=intento, entregado_en=_ts(t_int))
                break
            cambio(t_int + demora, estado="intento_fallido", intentos=intento)
            if intento == 3:
                cambio(_h(siguiente_habil(t_int.date(), 1), r.uniform(10, 16)), estado="devuelto")
                break
            courier = int(r.integers(*z["couriers"])) if r.random() < 0.3 else courier
            inicio_ruta = _h(siguiente_habil(t_int.date(), 1), r.uniform(7.5, 9.5))
        self._emitir(pasos, qa=False)

    # ------------------------------------------------------------ incidentes en origen

    def _emitir(self, pasos: list[tuple[datetime, dict]], qa: bool) -> None:
        """Aplica los incidentes de origen, arma antes/después y guarda los eventos."""
        fila0 = pasos[0][1]
        gramos = (fila0["canal"] == "agencia"
                  and GRAMOS[0] <= datetime.fromisoformat(fila0["registrado_en"]) < GRAMOS[1])
        salida: list[tuple[datetime, dict]] = []
        for t, f in pasos:
            f = dict(f)
            if gramos and t < GRAMOS[2]:
                f["peso_kg"] = round(f["peso_kg"] * 1000, 1)
            if MAYUSCULAS[0] <= t < MAYUSCULAS[1]:
                f["estado"] = f["estado"].upper()
            salida.append((t, f))
        if gramos:
            self.manifiesto["peso_en_gramos"].append(fila0["id_envio"])
            self._correccion(salida, GRAMOS[2], lambda f: f.update(peso_kg=round(f["peso_kg"] / 1000, 2)),
                             lambda f: f["peso_kg"] > 70)
        self._correccion(salida, MAYUSCULAS[2], lambda f: f.update(estado=f["estado"].lower()),
                         lambda f: f["estado"].isupper())
        if qa:
            self.manifiesto["envios_qa"].append(fila0["id_envio"])
            t_ultimo = salida[-1][0]
            lunes = t_ultimo.date() + timedelta(days=(7 - t_ultimo.weekday()) % 7 or 7)
            salida.append((_h(lunes, 3 + self.rng.random() * 0.2), None))

        antes = None
        for t, f in salida:
            if t >= self.fin:
                break
            if f is not None and t < ALTER_FRANJA:
                f = {k: v for k, v in f.items() if k != "franja_horaria"}
            elif f is not None:
                f = dict(f)
            op = "c" if antes is None else ("d" if f is None else "u")
            self.eventos.append({"t": t, "op": op, "antes": antes, "despues": f,
                                 "id": fila0["id_envio"]})
            if op == "d":
                self.manifiesto["borrados"].append(fila0["id_envio"])
                break
            antes = f

    @staticmethod
    def _correccion(salida, t_fix: datetime, arreglar, malo) -> None:
        """Si al momento del fix el registro sigue malo, el script de origen lo corrige con un UPDATE."""
        ultimo = None
        for i, (t, f) in enumerate(salida):
            if t < t_fix:
                ultimo = i
        if ultimo is None or not malo(salida[ultimo][1]):
            return
        f = dict(salida[ultimo][1])
        arreglar(f)
        f["actualizado_en"] = _ts(t_fix)
        salida.insert(ultimo + 1, (t_fix, f))
        # lo que viene después ya sale corregido de origen (o del incidente terminado)

    # ------------------------------------------------------------ conector

    def simular(self) -> None:
        id_envio = 1
        d = self.desde
        while d <= self.hasta:
            f = DIA_SEMANA[d.weekday()] * CAMPANIA.get(d, 1.0) * (1 + 0.004 * (d - INICIO).days / 7)
            if not es_habil(d) and d.weekday() != 6:
                f *= 0.5
            n = self.rng.poisson(ENVIOS_DIA * self.escala * f)
            for _ in range(n):
                self._envio(id_envio, d)
                id_envio += 1
            d += timedelta(days=1)
        self.eventos.sort(key=lambda e: (e["t"], e["id"]))
        lsn = 81_400_000
        for e in self.eventos:
            lsn += int(self.rng.integers(1, 4))
            e["lsn"] = lsn

    def escribir(self, directorio: Path) -> dict:
        r = self.rng
        dir_cdc = directorio / "cdc"
        shutil.rmtree(dir_cdc, ignore_errors=True)
        por_lote: dict[str, list[dict]] = defaultdict(list)
        ultimo_lote = lote_de(self.fin - timedelta(seconds=1))
        tarde = dup = 0
        for e in self.eventos:
            lote = lote_de(e["t"])
            u = r.random()
            if u < 0.013:
                lote, tarde = lote_siguiente(lote), tarde + 1
            elif u < 0.016:
                lote, tarde = lote_siguiente(lote, int(r.integers(2, 5))), tarde + 1
            if lote > ultimo_lote:
                lote = ultimo_lote
            por_lote[lote].append(e)
            if r.random() < 0.002:
                por_lote[lote_siguiente(lote) if lote < ultimo_lote else lote].append(e)
                dup += 1
        # reinicios del conector: reenvía las últimas dos horas del lote anterior
        for lote in REINICIOS:
            previo = lote_siguiente(lote, -1)
            if lote not in por_lote and previo not in por_lote:
                continue
            limite = datetime.strptime(previo, "%Y-%m-%dT%H") - timedelta(hours=2)
            reenviados = [e for e in por_lote.get(previo, []) if e["t"] >= limite]
            por_lote[lote].extend(reenviados)
            dup += len(reenviados)
            self.manifiesto["reinicios"].append({"lote": lote, "reenviados": len(reenviados)})

        for lote, evs in por_lote.items():
            carpeta = dir_cdc / f"lote={lote}"
            carpeta.mkdir(parents=True, exist_ok=True)
            partes = [[], []]
            for e in evs:  # dos tareas del conector, cada una con sus llaves
                partes[e["id"] % 2].append(e)
            for i, parte in enumerate(partes):
                if not parte:
                    continue
                with gzip.open(carpeta / f"parte-{i}.jsonl.gz", "wt", encoding="utf-8") as fh:
                    for e in parte:
                        utc = (e["t"] + timedelta(hours=5)).replace(tzinfo=timezone.utc)  # Lima es UTC-5
                        ms = int(utc.timestamp() * 1000)
                        fh.write(json.dumps({"lsn": e["lsn"], "op": e["op"], "ts_ms": ms,
                                             "fuente": {"db": "kallpa_oltp", "tabla": "public.envios"},
                                             "antes": e["antes"], "despues": e["despues"]},
                                            ensure_ascii=False) + "\n")

        # estado final en origen: último después de cada envío que no se borró
        final = {}
        for e in self.eventos:
            if e["t"] >= self.fin:
                continue
            final[e["id"]] = e["despues"]
        filas = [f for f in final.values() if f is not None]
        df = pd.DataFrame(filas)
        if "franja_horaria" not in df:
            df["franja_horaria"] = None
        for c in ("registrado_en", "entregado_en", "actualizado_en"):
            df[c] = pd.to_datetime(df[c])
        df["fecha_promesa"] = pd.to_datetime(df["fecha_promesa"]).dt.date
        (directorio / "origen").mkdir(parents=True, exist_ok=True)
        df.to_parquet(directorio / "origen" / "envios.parquet", index=False)

        resumen = {
            "desde": self.desde.isoformat(), "hasta": self.hasta.isoformat(),
            "envios": len(final), "eventos": len(self.eventos), "lotes": len(por_lote),
            "eventos_tarde": tarde, "eventos_duplicados": dup,
            **{k: v for k, v in self.manifiesto.items()},
        }
        (directorio / "origen" / "manifiesto.json").write_text(json.dumps(resumen, indent=1), encoding="utf-8")
        return resumen


_PERFIL_HORA = np.array([0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 0.8, 1.6, 2.6, 3.4, 3.6,
                         3.3, 3.0, 3.2, 3.5, 3.6, 3.4, 3.0, 2.4, 1.8, 1.3, 0.8, 0.4])
_PERFIL_HORA = _PERFIL_HORA / _PERFIL_HORA.sum()


def generar(directorio: Path = DIR_DEFECTO, escala: float = 1.0, seed: int = 26,
            desde: date = INICIO, hasta: date = FIN) -> dict:
    sim = Simulador(escala, seed, desde, hasta)
    sim.simular()
    return sim.escribir(Path(directorio))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", type=Path, default=DIR_DEFECTO)
    p.add_argument("--escala", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=26)
    p.add_argument("--desde", type=date.fromisoformat, default=INICIO)
    p.add_argument("--hasta", type=date.fromisoformat, default=FIN)
    a = p.parse_args()
    r = generar(a.dir, a.escala, a.seed, a.desde, a.hasta)
    print(f"{r['envios']:,} envíos · {r['eventos']:,} eventos · {r['lotes']} lotes · "
          f"{r['eventos_tarde']:,} tardíos · {r['eventos_duplicados']:,} duplicados")


if __name__ == "__main__":
    main()
