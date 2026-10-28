"""
Genera los datos de "Boticas Alameda", una cadena ficticia de 24 boticas en Lima,
el norte y el sur del país, con venta y stock diario por local y producto.

Primero se simula la demanda (lo que la gente quiso comprar) y después la
reposición con la regla que usa hoy la cadena: cada lunes se pide hasta cubrir
N días del promedio de venta de las últimas 4 semanas. Lo que se vende es lo que
había en anaquel, así que los quiebres de stock aparecen solos cuando la demanda
sube más rápido que ese promedio (invierno, dengue) o cuando un proveedor falla.

Patrones que trae la base:
  - invierno: antigripales y jarabes se duplican en Lima entre junio y agosto;
    en el norte casi no se nota; el invierno de 2025 fue más fuerte
  - verano: protector solar, rehidratantes y repelentes
  - brotes de dengue en el norte (fuerte en 2024, leve en 2025, moderado en 2026):
    suben repelentes y paracetamol, no el ibuprofeno
  - crónicos (losartán, metformina) se compran al inicio de mes
  - quincena en pañales y cuidado personal, antiácidos el 1 de enero y en Fiestas Patrias
  - promociones con alza durante la campaña y bajón después en lo que se puede almacenar
  - cuatro desabastecimientos de proveedor y un local nuevo (Carabayllo, jun-25)

Uso:
    python datos/generar_datos.py                  # base completa (~15 s)
    python datos/generar_datos.py --escala 0.25    # menos locales y productos, para pruebas
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from demanda.calendario import dia_de_la_madre, es_feriado, es_quincena  # noqa: E402

RUTA_DEFECTO = Path(__file__).parent / "boticas.duckdb"
FECHA_INICIO = date(2024, 1, 1)
FECHA_FIN = date(2026, 9, 30)
FIN_PLAN_PROMOS = date(2026, 12, 31)

# --------------------------------------------------------------------------
# Catálogos
# --------------------------------------------------------------------------

LOCALES = [
    # nombre, distrito, ciudad, región, formato, apertura
    ("Alameda Miraflores", "Miraflores", "Lima", "Lima", "avenida", "2016-04-11"),
    ("Alameda San Isidro", "San Isidro", "Lima", "Lima", "centro comercial", "2018-09-03"),
    ("Alameda Surco", "Santiago de Surco", "Lima", "Lima", "avenida", "2015-06-22"),
    ("Alameda La Molina", "La Molina", "Lima", "Lima", "centro comercial", "2019-02-18"),
    ("Alameda San Borja", "San Borja", "Lima", "Lima", "barrio", "2017-08-07"),
    ("Alameda Jesús María", "Jesús María", "Lima", "Lima", "barrio", "2016-11-14"),
    ("Alameda Lince", "Lince", "Lima", "Lima", "avenida", "2018-03-05"),
    ("Alameda San Miguel", "San Miguel", "Lima", "Lima", "centro comercial", "2017-05-29"),
    ("Alameda Los Olivos", "Los Olivos", "Lima", "Lima", "avenida", "2016-01-25"),
    ("Alameda Comas", "Comas", "Lima", "Lima", "barrio", "2019-10-21"),
    ("Alameda SMP", "San Martín de Porres", "Lima", "Lima", "barrio", "2018-07-16"),
    ("Alameda SJL", "San Juan de Lurigancho", "Lima", "Lima", "avenida", "2017-03-13"),
    ("Alameda Ate", "Ate", "Lima", "Lima", "avenida", "2020-02-10"),
    ("Alameda Chorrillos", "Chorrillos", "Lima", "Lima", "barrio", "2019-05-06"),
    ("Alameda VES", "Villa El Salvador", "Lima", "Lima", "barrio", "2021-09-13"),
    ("Alameda Callao", "Callao", "Callao", "Lima", "avenida", "2018-12-03"),
    ("Alameda Carabayllo", "Carabayllo", "Lima", "Lima", "barrio", "2025-06-02"),
    ("Alameda Piura", "Piura", "Piura", "Norte", "avenida", "2019-08-19"),
    ("Alameda Sullana", "Sullana", "Piura", "Norte", "barrio", "2021-04-26"),
    ("Alameda Chiclayo", "Chiclayo", "Chiclayo", "Norte", "avenida", "2018-10-08"),
    ("Alameda Trujillo", "Trujillo", "Trujillo", "Norte", "centro comercial", "2019-11-25"),
    ("Alameda Arequipa", "Cercado", "Arequipa", "Sur", "avenida", "2017-09-18"),
    ("Alameda Yanahuara", "Yanahuara", "Arequipa", "Sur", "barrio", "2020-07-06"),
    ("Alameda Cusco", "Wanchaq", "Cusco", "Sur", "avenida", "2021-01-18"),
]

# nombre, categoría, precio S/ 2024, venta base (u/día en un local promedio),
# perfil estacional, amplitud, sensibilidad al dengue, ¿entra en promociones?, ¿se puede almacenar?
PRODUCTOS = [
    ("Paracetamol 500 mg x 10 tab", "Analgésicos", 2.50, 14.0, "plana", 0.0, 1.3, False, False),
    ("Ibuprofeno 400 mg x 10 tab", "Analgésicos", 3.20, 9.0, "plana", 0.0, 0.0, False, False),
    ("Naproxeno 550 mg x 10 tab", "Analgésicos", 6.90, 4.0, "plana", 0.0, 0.0, False, False),
    ("Diclofenaco gel 50 g", "Analgésicos", 14.90, 1.6, "plana", 0.0, 0.0, True, False),
    ("Paracetamol jarabe infantil 120 ml", "Analgésicos", 8.50, 3.0, "invierno", 0.6, 0.8, False, False),
    ("Antigripal x 10 tab", "Respiratorio", 9.90, 5.0, "invierno", 1.6, 0.0, True, False),
    ("Jarabe para la tos adulto 120 ml", "Respiratorio", 18.90, 2.5, "invierno", 1.8, 0.0, True, False),
    ("Jarabe para la tos infantil 100 ml", "Respiratorio", 16.50, 2.0, "invierno", 2.0, 0.0, False, False),
    ("Ambroxol jarabe 120 ml", "Respiratorio", 12.90, 2.2, "invierno", 1.5, 0.0, False, False),
    ("Descongestionante nasal 15 ml", "Respiratorio", 15.90, 1.8, "invierno", 1.3, 0.0, False, False),
    ("Pastillas para la garganta x 12", "Respiratorio", 7.50, 3.5, "invierno", 1.4, 0.0, True, False),
    ("Loratadina 10 mg x 10 tab", "Respiratorio", 4.50, 4.0, "primavera", 0.5, 0.0, False, False),
    ("Salbutamol inhalador 100 mcg", "Respiratorio", 22.90, 0.8, "invierno", 0.9, 0.0, False, False),
    ("Sales de rehidratación oral x 1", "Gastrointestinal", 2.20, 6.0, "verano", 0.9, 0.7, False, False),
    ("Sal de frutas sobre x 1", "Gastrointestinal", 1.50, 7.0, "fiestas", 0.0, 0.0, False, False),
    ("Omeprazol 20 mg x 10 cap", "Gastrointestinal", 5.50, 5.0, "plana", 0.0, 0.0, False, False),
    ("Loperamida 2 mg x 6 tab", "Gastrointestinal", 4.90, 2.0, "verano", 0.7, 0.0, False, False),
    ("Bebida rehidratante 625 ml", "Gastrointestinal", 4.90, 5.0, "verano", 0.9, 0.6, True, False),
    ("Simeticona gotas 15 ml", "Gastrointestinal", 11.90, 1.2, "plana", 0.0, 0.0, False, False),
    ("Losartán 50 mg x 30 tab", "Crónicos", 12.90, 3.5, "inicio_mes", 0.0, 0.0, False, False),
    ("Metformina 850 mg x 30 tab", "Crónicos", 9.90, 3.0, "inicio_mes", 0.0, 0.0, False, False),
    ("Atorvastatina 20 mg x 30 tab", "Crónicos", 19.90, 1.8, "inicio_mes", 0.0, 0.0, False, False),
    ("Levotiroxina 100 mcg x 50 tab", "Crónicos", 24.90, 1.0, "inicio_mes", 0.0, 0.0, False, False),
    ("Amlodipino 5 mg x 30 tab", "Crónicos", 8.90, 2.0, "inicio_mes", 0.0, 0.0, False, False),
    ("Vitamina C 1 g efervescente x 10", "Vitaminas", 13.90, 2.8, "escolar_invierno", 0.6, 0.0, True, True),
    ("Multivitamínico adulto x 30", "Vitaminas", 39.90, 0.9, "escolar", 0.4, 0.0, True, True),
    ("Multivitamínico infantil jarabe 240 ml", "Vitaminas", 29.90, 1.0, "escolar_invierno", 0.6, 0.0, True, True),
    ("Zinc + vitamina C x 30", "Vitaminas", 24.90, 0.7, "invierno", 0.8, 0.0, True, True),
    ("Sulfato ferroso jarabe 180 ml", "Vitaminas", 9.90, 0.9, "plana", 0.0, 0.0, False, False),
    ("Protector solar FPS 50 crema 60 g", "Dermo y solar", 49.90, 1.2, "verano", 2.5, 0.0, True, True),
    ("Protector solar FPS 50 infantil spray", "Dermo y solar", 59.90, 0.5, "verano", 3.0, 0.0, True, False),
    ("Bloqueador labial FPS 30", "Dermo y solar", 12.90, 0.8, "verano", 1.5, 0.0, False, False),
    ("Crema hidratante corporal 400 ml", "Dermo y solar", 24.90, 1.0, "invierno", 0.5, 0.0, True, True),
    ("Repelente spray 120 ml", "Dermo y solar", 21.90, 1.0, "verano", 1.0, 3.0, True, False),
    ("Repelente crema infantil 60 g", "Dermo y solar", 18.90, 0.5, "verano", 0.8, 3.0, False, False),
    ("Pañales talla M x 40", "Bebé", 44.90, 2.5, "quincena", 0.0, 0.0, True, True),
    ("Pañales talla G x 40", "Bebé", 46.90, 2.6, "quincena", 0.0, 0.0, True, True),
    ("Toallitas húmedas x 100", "Bebé", 9.90, 3.0, "quincena", 0.0, 0.0, True, True),
    ("Fórmula infantil etapa 1 800 g", "Bebé", 79.90, 0.7, "quincena", 0.0, 0.0, False, True),
    ("Crema antipañalitis 60 g", "Bebé", 15.90, 1.0, "plana", 0.0, 0.0, False, False),
    ("Alcohol 70° 1 L", "Cuidado personal", 9.90, 3.0, "plana", 0.0, 0.0, False, False),
    ("Shampoo anticaspa 375 ml", "Cuidado personal", 21.90, 1.2, "quincena", 0.0, 0.0, True, True),
    ("Cepillo dental x 2", "Cuidado personal", 8.90, 1.8, "navidad", 0.0, 0.0, True, False),
    ("Pasta dental 150 ml", "Cuidado personal", 7.90, 3.0, "quincena", 0.0, 0.0, True, True),
    ("Desodorante roll-on 50 ml", "Cuidado personal", 12.90, 1.8, "quincena", 0.0, 0.0, True, True),
    ("Termómetro digital", "Equipos", 19.90, 0.18, "invierno", 1.2, 0.0, False, False),
    ("Tensiómetro digital de brazo", "Equipos", 129.90, 0.06, "regalo", 0.0, 0.0, False, False),
    ("Glucómetro + 10 tiras", "Equipos", 89.90, 0.05, "regalo", 0.0, 0.0, False, False),
]

MARGEN = {"Analgésicos": 0.38, "Respiratorio": 0.35, "Gastrointestinal": 0.33, "Crónicos": 0.30,
          "Vitaminas": 0.42, "Dermo y solar": 0.40, "Bebé": 0.18, "Cuidado personal": 0.32, "Equipos": 0.28}

FORMATO_BASE = {"avenida": 1.7, "centro comercial": 1.4, "barrio": 1.1}
# lunes a domingo
DIA_SEMANA = {
    "barrio": [1.02, 1.0, 1.0, 1.0, 1.03, 1.02, 0.85],
    "avenida": [1.05, 1.02, 1.0, 1.0, 1.04, 0.98, 0.75],
    "centro comercial": [0.85, 0.85, 0.88, 0.90, 1.0, 1.25, 1.30],
}
FERIADO = {"barrio": 0.90, "avenida": 0.85, "centro comercial": 1.15}

# qué tanto pega cada estación en cada región
REGION_ESTACION = {
    "invierno": {"Lima": 1.0, "Sur": 0.9, "Norte": 0.35},
    "verano": {"Lima": 1.0, "Norte": 1.1, "Sur": 0.5},
    "primavera": {"Lima": 1.0, "Sur": 0.6, "Norte": 0.6},
}
# el invierno cambia de un año a otro: 2025 vino más fuerte y 2026 se adelantó
INVIERNO = {2023: (198, 1.0), 2024: (198, 1.0), 2025: (192, 1.30), 2026: (184, 1.10)}
# brotes de dengue en el norte: pico (mes, día), ancho en días, intensidad
DENGUE = {2024: ((4, 8), 15, 1.3), 2025: ((3, 25), 14, 0.3), 2026: ((4, 15), 14, 0.8)}
DENGUE_CIUDAD = {"Piura": 1.0, "Chiclayo": 0.8, "Trujillo": 0.6}
# desabastecimiento del proveedor: los pedidos de esas fechas no llegan
DESABASTECIMIENTOS = [
    ("Sales de rehidratación oral x 1", "2024-04-01", "2024-04-21"),
    ("Jarabe para la tos infantil 100 ml", "2025-07-07", "2025-07-27"),
    ("Protector solar FPS 50 infantil spray", "2026-01-12", "2026-01-25"),
    ("Losartán 50 mg x 30 tab", "2026-02-09", "2026-02-22"),
]

# regla de reposición actual: pedido semanal (lunes) hasta cubrir N días del promedio de 28 días
LEAD_TIME = {"Lima": 2, "Norte": 4, "Sur": 4}
COBERTURA = {"Lima": 12, "Norte": 15, "Sur": 15}
STOCK_MINIMO = 2  # exhibición


# --------------------------------------------------------------------------
# Demanda
# --------------------------------------------------------------------------

def _campana(doy: np.ndarray, pico: float, ancho: float) -> np.ndarray:
    """Curva gaussiana sobre el año (circular: diciembre está al lado de enero)."""
    d = np.abs(doy - pico)
    d = np.minimum(d, 365 - d)
    return np.exp(-0.5 * (d / ancho) ** 2)


def _estacionalidad(fechas: pd.DatetimeIndex, perfil: str, amp: float, region: str,
                    ciudad: str) -> np.ndarray:
    doy = fechas.dayofyear.to_numpy().astype(float)
    f = np.ones(len(fechas))
    if perfil in ("invierno", "escolar_invierno"):
        k = REGION_ESTACION["invierno"][region]
        for anio, (pico, fuerza) in INVIERNO.items():
            # la campaña de un año también toca diciembre/enero vecinos: se acota por año
            mascara = fechas.year == anio
            f[mascara] += amp * k * fuerza * _campana(doy[mascara], pico, 34)
    if perfil == "verano":
        k = REGION_ESTACION["verano"][region]
        if ciudad == "Arequipa":
            k *= 1.6  # radiación alta todo el año
        f += amp * k * _campana(doy, 35, 38)
    if perfil in ("escolar", "escolar_invierno"):
        f += 0.45 * _campana(doy, 69, 16)  # regreso a clases
    if perfil == "primavera":
        f += amp * REGION_ESTACION["primavera"][region] * _campana(doy, 280, 30)
    dia = fechas.day.to_numpy()
    if perfil == "inicio_mes":
        f *= np.where(dia <= 5, 1.28, np.where(dia >= 26, 0.88, 1.0))
    if perfil == "quincena":
        f *= np.where(es_quincena(fechas), 1.15, 1.0)
    if perfil == "fiestas":
        md = fechas.strftime("%m-%d")
        f *= pd.Series(md).map({"01-01": 3.0, "01-02": 1.8, "07-29": 2.0, "07-30": 1.4,
                                "12-25": 1.8, "12-26": 1.5}).fillna(1.0).to_numpy()
    if perfil == "navidad":
        f *= np.where((fechas.month == 12) & (dia >= 10) & (dia <= 24), 1.35, 1.0)
    if perfil == "regalo":
        madre = pd.DatetimeIndex([dia_de_la_madre(a) for a in sorted(set(fechas.year))])
        cerca = np.zeros(len(fechas), dtype=bool)
        for m in madre:
            cerca |= (fechas >= m - pd.Timedelta(days=8)) & (fechas <= m)
        f *= np.where(cerca, 2.6, 1.0)
        f *= np.where((fechas.month == 12) & (dia >= 12) & (dia <= 24), 1.8, 1.0)
    return f


def _dengue(fechas: pd.DatetimeIndex, ciudad: str, region: str) -> np.ndarray:
    k = DENGUE_CIUDAD.get(ciudad, 0.0) if region == "Norte" else 0.0
    if ciudad == "Sullana":
        k = 1.0
    if region == "Lima":
        k = 0.06
    curva = np.zeros(len(fechas))
    for anio, ((mes, dia), ancho, fuerza) in DENGUE.items():
        pico = pd.Timestamp(anio, mes, dia)
        dias = (fechas - pico).days.to_numpy()
        curva += fuerza * np.exp(-0.5 * (dias / ancho) ** 2)
    return k * curva


def _promociones(rng: np.random.Generator, productos: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for p in productos.itertuples():
        if not p.en_promociones:
            continue
        for anio in range(FECHA_INICIO.year, FIN_PLAN_PROMOS.year + 1):
            n = rng.integers(3, 6)
            inicios = sorted(rng.choice(np.arange(5, 340), size=n, replace=False))
            fin_anterior = -1
            for ini in inicios:
                if ini <= fin_anterior + 21:  # al menos 3 semanas entre campañas
                    continue
                duracion = int(rng.choice([7, 10, 14]))
                inicio = pd.Timestamp(anio, 1, 1) + pd.Timedelta(days=int(ini))
                fin = inicio + pd.Timedelta(days=duracion - 1)
                filas.append((p.id_producto, inicio, fin, float(rng.choice([0.15, 0.20, 0.25, 0.30]))))
                fin_anterior = ini + duracion
    promos = pd.DataFrame(filas, columns=["id_producto", "inicio", "fin", "descuento"])
    promos = promos[promos.inicio.dt.date <= FIN_PLAN_PROMOS].reset_index(drop=True)
    promos.insert(0, "id_promocion", np.arange(1, len(promos) + 1))
    return promos


def _efecto_promos(fechas: pd.DatetimeIndex, promos: pd.DataFrame, productos: pd.DataFrame
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (descuento, multiplicador de demanda) por día y producto."""
    n_p = len(productos)
    desc = np.zeros((len(fechas), n_p))
    mult = np.ones((len(fechas), n_p))
    pos = {pid: i for i, pid in enumerate(productos.id_producto)}
    for pr in promos.itertuples():
        j = pos[pr.id_producto]
        prod = productos.iloc[j]
        dentro = (fechas >= pr.inicio) & (fechas <= pr.fin)
        desc[dentro, j] = pr.descuento
        mult[dentro, j] *= (1 - pr.descuento) ** (-prod.elasticidad)
        if prod.almacenable:
            # quien se abasteció en la promo no vuelve en un par de semanas
            dias = (fechas - pr.fin).days.to_numpy()
            despues = (dias >= 1) & (dias <= 14)
            mult[despues, j] *= 1 - 0.30 * (1 - (dias[despues] - 1) / 14)
    return desc, mult


# --------------------------------------------------------------------------
# Generación
# --------------------------------------------------------------------------

def _seleccion(escala: float) -> tuple[list[int], list[int]]:
    """Subconjunto de locales y productos para bases chicas (siempre incluye Lima y el norte)."""
    if escala >= 1:
        return list(range(len(LOCALES))), list(range(len(PRODUCTOS)))
    n_l = max(5, round(len(LOCALES) * escala))
    n_p = max(10, round(len(PRODUCTOS) * escala))
    locales = sorted(set(np.linspace(0, len(LOCALES) - 1, n_l).round().astype(int)) | {16, 17})
    productos = sorted(set(np.linspace(0, len(PRODUCTOS) - 1, n_p).round().astype(int)) | {0, 5, 33})
    return locales, productos


def generar(ruta: Path = RUTA_DEFECTO, escala: float = 1.0, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    ruta = Path(ruta)
    idx_l, idx_p = _seleccion(escala)

    locales = pd.DataFrame([LOCALES[i] for i in idx_l],
                           columns=["nombre", "distrito", "ciudad", "region", "formato", "apertura"])
    locales.insert(0, "id_local", np.arange(1, len(locales) + 1))
    locales["apertura"] = pd.to_datetime(locales.apertura)
    locales["lead_time_dias"] = locales.region.map(LEAD_TIME)
    locales["cobertura_dias"] = locales.region.map(COBERTURA)

    productos = pd.DataFrame([PRODUCTOS[i] for i in idx_p],
                             columns=["nombre", "categoria", "precio_lista", "base", "perfil", "amp",
                                      "dengue", "en_promociones", "almacenable"])
    productos.insert(0, "id_producto", np.arange(1, len(productos) + 1))
    productos["costo"] = (productos.precio_lista * (1 - productos.categoria.map(MARGEN))).round(2)
    productos["elasticidad"] = rng.uniform(1.8, 2.8, len(productos)).round(2)

    fechas = pd.date_range(FECHA_INICIO, FECHA_FIN, freq="D")
    n_d, n_l, n_p = len(fechas), len(locales), len(productos)

    promos = _promociones(rng, productos)
    descuento, mult_promo = _efecto_promos(fechas, promos, productos)

    # ----- demanda esperada (día x local x producto)
    anios = (fechas - pd.Timestamp(FECHA_INICIO)).days.to_numpy() / 365.25
    tendencia = 1.055 ** anios
    choque_dia = np.exp(rng.normal(0, 0.04, n_d))  # clima, feriados largos, etc.
    lam = np.zeros((n_d, n_l, n_p))
    feriado = es_feriado(fechas)
    dow = fechas.dayofweek.to_numpy()
    for i, loc in enumerate(locales.itertuples()):
        base_local = FORMATO_BASE[loc.formato] * np.exp(rng.normal(0, 0.15))
        f_dia = np.array(DIA_SEMANA[loc.formato])[dow] * np.where(feriado, FERIADO[loc.formato], 1.0)
        dias_abierto = (fechas - loc.apertura).days.to_numpy()
        arranque = np.where(dias_abierto < 0, 0.0, 1 - 0.55 * np.exp(-np.maximum(dias_abierto, 0) / 60))
        dengue = _dengue(fechas, loc.ciudad, loc.region)
        for j, p in enumerate(productos.itertuples()):
            gusto = np.exp(rng.normal(0, 0.20))  # cada local tiene su mezcla
            est = _estacionalidad(fechas, p.perfil, p.amp, loc.region, loc.ciudad)
            f = f_dia.copy()
            if p.categoria == "Crónicos":
                f *= np.where(dow >= 5, 0.85, 1.0) * np.where(feriado, 0.80, 1.0)
            lam[:, i, j] = (p.base * base_local * gusto * tendencia * choque_dia * f * est
                            * (1 + p.dengue * dengue) * mult_promo[:, j] * arranque)

    # persistencia local: semanas buenas y malas por serie (AR(1) en log)
    ruido = np.zeros((n_d, n_l, n_p))
    e = rng.normal(0, 0.10, (n_l, n_p))
    for t in range(n_d):
        e = 0.85 * e + rng.normal(0, 0.06, (n_l, n_p))
        ruido[t] = e
    lam *= np.exp(ruido - 0.5 * 0.06 ** 2 / (1 - 0.85 ** 2))
    demanda = rng.poisson(lam * rng.gamma(8.0, 1 / 8.0, lam.shape)).astype(np.int64)

    # ----- reposición con la regla actual
    abierto = (fechas.to_numpy()[:, None] >= locales.apertura.to_numpy()[None, :])  # (d, l)
    lead = locales.lead_time_dias.to_numpy()
    cobertura = locales.cobertura_dias.to_numpy()
    sin_proveedor = np.zeros((n_d, n_p), dtype=bool)
    pos_p = {n: j for j, n in enumerate(productos.nombre)}
    for nombre, ini, fin in DESABASTECIMIENTOS:
        if nombre in pos_p:
            sin_proveedor[(fechas >= ini) & (fechas <= fin), pos_p[nombre]] = True

    ventas = np.zeros_like(demanda)
    stock_cierre = np.zeros_like(demanda)
    recibido = np.zeros_like(demanda)
    llegadas = np.zeros((n_d + 10, n_l, n_p), dtype=np.int64)
    en_transito = np.zeros((n_l, n_p), dtype=np.int64)
    # arranque: stock para la cobertura con la demanda esperada de enero
    prom_inicial = lam[:28].mean(axis=0)
    stock = np.ceil(prom_inicial * cobertura[:, None]).astype(np.int64)
    historia = np.repeat(prom_inicial[None], 28, axis=0)  # ventana móvil de 28 días
    pedidos = []
    for t in range(n_d):
        abre_hoy = abierto[t] & ~(abierto[t - 1] if t else np.zeros(n_l, bool))
        if t and abre_hoy.any():
            prom = lam[t:t + 28, abre_hoy].mean(axis=0)
            stock[abre_hoy] = np.ceil(prom * cobertura[abre_hoy, None])
            historia[:, abre_hoy] = prom
        llega = llegadas[t]
        stock += llega
        en_transito -= llega
        recibido[t] = llega
        vende = np.minimum(demanda[t], stock) * abierto[t][:, None]
        stock -= vende
        ventas[t] = vende
        stock_cierre[t] = stock
        historia[t % 28] = vende
        if dow[t] == 0:  # lunes: pedido
            objetivo = np.maximum(np.ceil(historia.mean(axis=0) * cobertura[:, None]), STOCK_MINIMO)
            pedido = np.maximum(objetivo - stock - en_transito, 0).astype(np.int64)
            pedido[:, sin_proveedor[t]] = 0
            pedido[~abierto[t]] = 0
            for i in range(n_l):
                llegadas[t + lead[i], i] += pedido[i]
            en_transito += pedido
            ii, jj = np.nonzero(pedido)
            pedidos.append(pd.DataFrame({"fecha_pedido": fechas[t], "id_local": locales.id_local.to_numpy()[ii],
                                         "id_producto": productos.id_producto.to_numpy()[jj],
                                         "unidades": pedido[ii, jj],
                                         "fecha_llegada": fechas[t] + pd.to_timedelta(lead[ii], unit="D")}))

    # ----- tablas
    d_idx, l_idx, p_idx = np.meshgrid(np.arange(n_d), np.arange(n_l), np.arange(n_p), indexing="ij")
    mask = abierto[d_idx, l_idx].ravel()
    anio_precio = 1.035 ** (fechas.year.to_numpy() - FECHA_INICIO.year)
    precio = (productos.precio_lista.to_numpy()[None, :] * anio_precio[:, None] * (1 - descuento))
    ventas_df = pd.DataFrame({
        "fecha": fechas.to_numpy()[d_idx.ravel()][mask],
        "id_local": locales.id_local.to_numpy()[l_idx.ravel()][mask],
        "id_producto": productos.id_producto.to_numpy()[p_idx.ravel()][mask],
        "unidades": ventas.ravel()[mask],
        "precio_unitario": precio[d_idx.ravel(), p_idx.ravel()][mask].round(2),
        "stock_cierre": stock_cierre.ravel()[mask],
        "unidades_recibidas": recibido.ravel()[mask],
    })
    latente = ventas_df[["fecha", "id_local", "id_producto"]].copy()
    latente["unidades"] = demanda.ravel()[mask]

    pedidos = pd.concat(pedidos, ignore_index=True)
    productos_out = productos[["id_producto", "nombre", "categoria", "precio_lista", "costo",
                               "almacenable"]].copy()
    if ruta.exists():
        ruta.unlink()
    con = duckdb.connect(str(ruta))
    for nombre, df in [("locales", locales), ("productos", productos_out), ("promociones", promos), ("pedidos", pedidos),
                       ("ventas_diarias", ventas_df), ("demanda_latente", latente)]:
        con.register("df_tmp", df)
        con.execute(f"CREATE TABLE {nombre} AS SELECT * FROM df_tmp")
        con.unregister("df_tmp")
    con.execute("CREATE TABLE feriados AS SELECT UNNEST(?::DATE[]) AS fecha",
                [[d for d in pd.to_datetime(fechas[feriado]).date]])
    comentarios = {
        "locales": "Boticas de la cadena. lead_time_dias y cobertura_dias son los de la regla actual de reposición.",
        "productos": "Catálogo. precio_lista es el de 2024; cada enero sube 3.5%.",
        "promociones": "Plan de campañas por producto, a nivel cadena. Incluye las planificadas hasta dic-2026.",
        "ventas_diarias": "Venta y stock por día, local y producto. stock_cierre = 0 significa quiebre: "
                          "ese día se vendió lo que había, no lo que se pidió.",
        "pedidos": "Órdenes de reposición de la regla actual. Las que llegan después del último día siguen en tránsito.",
        "demanda_latente": "Lo que se habría vendido con stock suficiente. Solo existe porque los datos son "
                           "sintéticos: sirve para evaluar el tratamiento de quiebres y simular políticas, "
                           "nunca para entrenar.",
        "feriados": "Feriados nacionales del periodo.",
    }
    for t, c in comentarios.items():
        con.execute(f"COMMENT ON TABLE {t} IS '{c}'")
    con.close()
    return ruta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--salida", type=Path, default=RUTA_DEFECTO)
    parser.add_argument("--escala", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    a = parser.parse_args()
    ruta = generar(a.salida, a.escala, a.seed)
    con = duckdb.connect(str(ruta), read_only=True)
    n, quiebres, u = con.execute(
        "SELECT COUNT(*), AVG((stock_cierre = 0)::INT), SUM(unidades) FROM ventas_diarias").fetchone()
    print(f"{ruta.name}: {n:,} filas · {u:,} unidades · {quiebres:.1%} de días con quiebre")
