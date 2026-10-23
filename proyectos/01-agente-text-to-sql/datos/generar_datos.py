"""
Genera la base de datos de "Minimarkets La Esquina", una cadena ficticia
de 24 tiendas en Lima y provincias.

Patrones que trae la base:
  - más ventas los fines de semana, en Fiestas Patrias y en diciembre
  - horas punta en la mañana, al mediodía y a la salida del trabajo
  - Yape y Plin le van ganando terreno al efectivo mes a mes
  - en provincia se paga más en efectivo que en Lima
  - alza de precios a inicios de 2026

Uso:
    python datos/generar_datos.py                  # base completa (~1 min)
    python datos/generar_datos.py --escala 0.05    # base chica para pruebas
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

RUTA_DEFECTO = Path(__file__).parent / "minimarkets.duckdb"
FECHA_INICIO = date(2025, 1, 1)
FECHA_FIN = date(2026, 9, 30)

# --------------------------------------------------------------------------
# Catálogos
# --------------------------------------------------------------------------

TIENDAS = [
    # nombre, distrito, ciudad, formato, fecha_apertura
    ("La Esquina Miraflores", "Miraflores", "Lima", "Estándar", "2019-03-15"),
    ("La Esquina Larco", "Miraflores", "Lima", "Express", "2021-08-02"),
    ("La Esquina San Isidro", "San Isidro", "Lima", "Express", "2020-01-20"),
    ("La Esquina Surco", "Santiago de Surco", "Lima", "Estándar", "2018-11-05"),
    ("La Esquina Higuereta", "Santiago de Surco", "Lima", "Express", "2022-04-11"),
    ("La Esquina Jesús María", "Jesús María", "Lima", "Estándar", "2019-07-01"),
    ("La Esquina Magdalena", "Magdalena del Mar", "Lima", "Express", "2021-02-14"),
    ("La Esquina Pueblo Libre", "Pueblo Libre", "Lima", "Estándar", "2020-09-09"),
    ("La Esquina San Miguel", "San Miguel", "Lima", "Estándar", "2018-05-23"),
    ("La Esquina Los Olivos", "Los Olivos", "Lima", "Estándar", "2019-10-30"),
    ("La Esquina Independencia", "Independencia", "Lima", "Estándar", "2021-06-18"),
    ("La Esquina Comas", "Comas", "Lima", "Estándar", "2022-09-05"),
    ("La Esquina SJL", "San Juan de Lurigancho", "Lima", "Estándar", "2020-03-02"),
    ("La Esquina Ate", "Ate", "Lima", "Estándar", "2021-11-22"),
    ("La Esquina La Molina", "La Molina", "Lima", "Express", "2023-01-16"),
    ("La Esquina Chorrillos", "Chorrillos", "Lima", "Estándar", "2022-02-07"),
    ("La Esquina VMT", "Villa María del Triunfo", "Lima", "Estándar", "2023-08-21"),
    ("La Esquina Callao", "Callao", "Callao", "Estándar", "2020-12-01"),
    ("La Esquina Arequipa Centro", "Cercado", "Arequipa", "Estándar", "2021-04-12"),
    ("La Esquina Cayma", "Cayma", "Arequipa", "Express", "2023-05-29"),
    ("La Esquina Trujillo", "Trujillo", "Trujillo", "Estándar", "2022-06-13"),
    ("La Esquina Chiclayo", "Chiclayo", "Chiclayo", "Estándar", "2023-03-06"),
    ("La Esquina Piura", "Piura", "Piura", "Estándar", "2025-05-19"),
    ("La Esquina Barranco", "Barranco", "Lima", "Express", "2025-09-08"),
]

CATEGORIAS = [
    # nombre, margen bruto típico
    ("Abarrotes", 0.18),
    ("Lácteos", 0.17),
    ("Bebidas", 0.27),
    ("Snacks y golosinas", 0.34),
    ("Limpieza del hogar", 0.28),
    ("Cuidado personal", 0.31),
    ("Panadería", 0.40),
    ("Frutas y verduras", 0.30),
    ("Cervezas y licores", 0.24),
    ("Congelados", 0.26),
]

# nombre, categoría, precio de lista 2025 (S/), popularidad relativa
PRODUCTOS = [
    ("Arroz extra 5 kg", "Abarrotes", 23.90, 6),
    ("Arroz extra 1 kg", "Abarrotes", 4.90, 9),
    ("Azúcar rubia 1 kg", "Abarrotes", 4.20, 8),
    ("Aceite vegetal 1 L", "Abarrotes", 9.50, 7),
    ("Fideo spaghetti 500 g", "Abarrotes", 3.30, 8),
    ("Fideo tallarín 500 g", "Abarrotes", 3.30, 6),
    ("Atún en trozos 170 g", "Abarrotes", 6.20, 7),
    ("Lentejas 500 g", "Abarrotes", 5.40, 3),
    ("Menestra frejol canario 500 g", "Abarrotes", 7.80, 3),
    ("Sal de mesa 1 kg", "Abarrotes", 1.80, 4),
    ("Avena 900 g", "Abarrotes", 8.90, 4),
    ("Café instantáneo 50 g", "Abarrotes", 9.90, 4),
    ("Mayonesa 400 g", "Abarrotes", 9.20, 4),
    ("Ají amarillo en pasta 200 g", "Abarrotes", 4.50, 3),
    ("Huevos pardos x 15", "Abarrotes", 10.90, 7),
    ("Leche evaporada 400 g", "Lácteos", 4.10, 10),
    ("Leche evaporada six pack", "Lácteos", 23.50, 4),
    ("Yogurt fresa 1 L", "Lácteos", 7.20, 6),
    ("Queso fresco 500 g", "Lácteos", 13.90, 4),
    ("Mantequilla 200 g", "Lácteos", 8.40, 3),
    ("Leche fresca UHT 1 L", "Lácteos", 5.60, 5),
    ("Gaseosa amarilla 1.5 L", "Bebidas", 6.50, 9),
    ("Gaseosa negra 1.5 L", "Bebidas", 6.30, 7),
    ("Gaseosa amarilla 500 ml", "Bebidas", 2.80, 9),
    ("Agua sin gas 625 ml", "Bebidas", 1.80, 10),
    ("Agua sin gas 2.5 L", "Bebidas", 3.90, 6),
    ("Bebida rehidratante 500 ml", "Bebidas", 3.50, 6),
    ("Jugo de naranja 1 L", "Bebidas", 5.90, 4),
    ("Chicha morada 1 L", "Bebidas", 4.90, 4),
    ("Bebida energizante 473 ml", "Bebidas", 5.50, 5),
    ("Té helado limón 500 ml", "Bebidas", 2.90, 4),
    ("Papas fritas clásicas 42 g", "Snacks y golosinas", 2.20, 9),
    ("Papas fritas familiar 180 g", "Snacks y golosinas", 7.90, 4),
    ("Chifles de plátano 100 g", "Snacks y golosinas", 3.50, 4),
    ("Galletas de soda x 6", "Snacks y golosinas", 2.90, 7),
    ("Galletas rellenas chocolate", "Snacks y golosinas", 1.50, 9),
    ("Chocolate de leche 30 g", "Snacks y golosinas", 2.50, 7),
    ("Caramelos de limón bolsa", "Snacks y golosinas", 3.90, 3),
    ("Maní salado 100 g", "Snacks y golosinas", 3.20, 4),
    ("Chicle menta x 5", "Snacks y golosinas", 1.00, 6),
    ("Detergente en polvo 2 kg", "Limpieza del hogar", 21.90, 4),
    ("Lejía 1 L", "Limpieza del hogar", 3.90, 5),
    ("Lavavajilla en pasta 500 g", "Limpieza del hogar", 4.60, 5),
    ("Papel higiénico x 4", "Limpieza del hogar", 6.90, 7),
    ("Papel toalla x 2", "Limpieza del hogar", 7.50, 3),
    ("Bolsas de basura x 20", "Limpieza del hogar", 5.90, 3),
    ("Limpiatodo lavanda 900 ml", "Limpieza del hogar", 6.40, 3),
    ("Shampoo 400 ml", "Cuidado personal", 15.90, 3),
    ("Jabón de tocador x 3", "Cuidado personal", 7.90, 4),
    ("Pasta dental 90 g", "Cuidado personal", 5.90, 5),
    ("Desodorante en barra", "Cuidado personal", 12.90, 3),
    ("Toallas higiénicas x 10", "Cuidado personal", 6.50, 4),
    ("Pañales talla G x 30", "Cuidado personal", 42.90, 2),
    ("Pan francés x 6", "Panadería", 2.40, 9),
    ("Pan de molde blanco", "Panadería", 8.90, 5),
    ("Keke de vainilla porción", "Panadería", 3.50, 4),
    ("Empanada de carne", "Panadería", 5.50, 5),
    ("Palta fuerte x kg", "Frutas y verduras", 9.90, 5),
    ("Plátano de seda x kg", "Frutas y verduras", 4.50, 6),
    ("Limón x kg", "Frutas y verduras", 6.90, 6),
    ("Papa amarilla x kg", "Frutas y verduras", 4.80, 5),
    ("Cebolla roja x kg", "Frutas y verduras", 3.90, 5),
    ("Tomate x kg", "Frutas y verduras", 4.20, 5),
    ("Mandarina x kg", "Frutas y verduras", 5.50, 3),
    ("Cerveza lata 355 ml", "Cervezas y licores", 4.20, 8),
    ("Cerveza six pack lata", "Cervezas y licores", 23.90, 5),
    ("Cerveza botella 620 ml", "Cervezas y licores", 6.90, 6),
    ("Pisco quebranta 700 ml", "Cervezas y licores", 39.90, 2),
    ("Vino tinto 750 ml", "Cervezas y licores", 29.90, 2),
    ("Ron 750 ml", "Cervezas y licores", 34.90, 2),
    ("Helado de vainilla 1 L", "Congelados", 14.90, 3),
    ("Paleta de helado", "Congelados", 2.50, 6),
    ("Nuggets de pollo 500 g", "Congelados", 16.90, 3),
    ("Hamburguesa de res x 4", "Congelados", 13.90, 3),
    ("Papas prefritas 1 kg", "Congelados", 11.90, 3),
]

NOMBRES = [
    "José", "Luis", "Carlos", "Juan", "Jorge", "Miguel", "César", "Víctor",
    "Renzo", "Diego", "Jhon", "Kevin", "Brayan", "Alonso", "Piero", "Gustavo",
    "María", "Rosa", "Carmen", "Ana", "Lucía", "Milagros", "Gabriela", "Fiorella",
    "Diana", "Karla", "Andrea", "Valeria", "Kiara", "Yesenia", "Pamela", "Sofía",
]
APELLIDOS = [
    "Quispe", "Flores", "Huamán", "Rojas", "Mamani", "Sánchez", "García",
    "Chávez", "Ramírez", "Torres", "Vásquez", "Mendoza", "Castillo", "Díaz",
    "Gutiérrez", "Ramos", "Espinoza", "Cruz", "Vargas", "Reyes", "Romero",
    "Paredes", "Salazar", "Ccori", "Condori", "Tello", "Benavides", "Saavedra",
]
SEGMENTOS = ["Frecuente", "Ocasional", "Nuevo"]
MEDIOS_PAGO = ["Efectivo", "Yape", "Plin", "Tarjeta de débito", "Tarjeta de crédito"]


# --------------------------------------------------------------------------
# Generadores
# --------------------------------------------------------------------------

def _tabla_tiendas() -> pd.DataFrame:
    df = pd.DataFrame(
        TIENDAS, columns=["nombre", "distrito", "ciudad", "formato", "fecha_apertura"]
    )
    df.insert(0, "id_tienda", range(1, len(df) + 1))
    df["fecha_apertura"] = pd.to_datetime(df["fecha_apertura"]).dt.date
    return df


def _tabla_categorias() -> pd.DataFrame:
    df = pd.DataFrame(CATEGORIAS, columns=["nombre", "margen"])
    df.insert(0, "id_categoria", range(1, len(df) + 1))
    return df[["id_categoria", "nombre"]], dict(zip(df["nombre"], df["margen"]))


def _tabla_productos(categorias: pd.DataFrame, margenes: dict, rng) -> pd.DataFrame:
    df = pd.DataFrame(PRODUCTOS, columns=["nombre", "categoria", "precio_lista", "popularidad"])
    df.insert(0, "id_producto", range(1, len(df) + 1))
    id_cat = dict(zip(categorias["nombre"], categorias["id_categoria"]))
    df["id_categoria"] = df["categoria"].map(id_cat)
    margen = df["categoria"].map(margenes) + rng.normal(0, 0.03, len(df))
    df["costo_unitario"] = (df["precio_lista"] * (1 - margen.clip(0.08, 0.6))).round(2)
    return df


def _tabla_clientes(n: int, tiendas: pd.DataFrame, rng) -> pd.DataFrame:
    nombres = rng.choice(NOMBRES, n)
    ap1 = rng.choice(APELLIDOS, n)
    ap2 = rng.choice(APELLIDOS, n)
    distritos = rng.choice(tiendas["distrito"].to_numpy(), n)
    dias = rng.integers(0, (FECHA_FIN - date(2022, 1, 1)).days, n)
    registro = pd.to_datetime("2022-01-01") + pd.to_timedelta(dias, unit="D")
    return pd.DataFrame({
        "id_cliente": np.arange(1, n + 1),
        "nombre_completo": [f"{a} {b} {c}" for a, b, c in zip(nombres, ap1, ap2)],
        "distrito": distritos,
        "fecha_registro": registro.date,
        "segmento": rng.choice(SEGMENTOS, n, p=[0.3, 0.5, 0.2]),
    })


def _factor_dia(fechas: pd.DatetimeIndex) -> np.ndarray:
    """Estacionalidad diaria: día de semana, quincena, Fiestas Patrias y diciembre."""
    dow = np.array([0.92, 0.90, 0.93, 0.97, 1.08, 1.22, 1.15])[fechas.day_of_week]
    mes = np.array([0.95, 0.93, 0.98, 0.97, 1.00, 0.99,
                    1.10, 1.01, 0.98, 1.00, 1.03, 1.25])[fechas.month - 1]
    quincena = np.where(np.isin(fechas.day, [15, 16, 30, 31, 1]), 1.08, 1.0)
    fiestas = np.where((fechas.month == 7) & np.isin(fechas.day, [27, 28, 29]), 1.35, 1.0)
    navidad = np.where((fechas.month == 12) & np.isin(fechas.day, [23, 24, 30, 31]), 1.40, 1.0)
    # crecimiento orgánico de ~6% anual
    t = (fechas - pd.Timestamp(FECHA_INICIO)).days.to_numpy() / 365
    return dow * mes * quincena * fiestas * navidad * (1 + 0.06 * t)


def _tabla_ventas(tiendas: pd.DataFrame, n_clientes: int, escala: float, rng) -> pd.DataFrame:
    fechas = pd.date_range(FECHA_INICIO, FECHA_FIN, freq="D")
    factor = _factor_dia(fechas)
    base_formato = {"Estándar": 34.0, "Express": 22.0}

    bloques = []
    for t in tiendas.itertuples():
        activa = fechas >= pd.Timestamp(t.fecha_apertura)
        base = base_formato[t.formato] * escala * rng.uniform(0.75, 1.3)
        # las tiendas nuevas tardan unos meses en madurar
        dias_abierta = (fechas - pd.Timestamp(t.fecha_apertura)).days.to_numpy()
        maduracion = np.clip(0.45 + dias_abierta / 240, 0.45, 1.0)
        lam = base * factor * maduracion * activa
        tickets = rng.poisson(lam)
        dias = np.repeat(fechas.to_numpy(), tickets)
        bloques.append(pd.DataFrame({
            "fecha": dias,
            "id_tienda": t.id_tienda,
            "ciudad": t.ciudad,
        }))
    v = pd.concat(bloques, ignore_index=True)
    n = len(v)

    # hora del ticket: picos a las 8-9, 13 y 19
    horas = np.concatenate([
        rng.normal(8.8, 1.0, n), rng.normal(13.2, 1.1, n), rng.normal(19.3, 1.4, n)
    ])
    elegir = rng.choice(3, n, p=[0.28, 0.32, 0.40])
    hora = horas.reshape(3, n)[elegir, np.arange(n)]
    # la tienda abre de 7:00 a 23:00; lo que cae fuera se "refleja" hacia adentro
    hora = np.where(hora < 7, 14 - hora, hora)
    hora = np.where(hora >= 23, 46 - hora, hora).clip(7, 22.99)
    segundos = (hora * 3600).astype(int)
    v["fecha_hora"] = v["fecha"] + pd.to_timedelta(segundos, unit="s")

    # medio de pago: la billetera digital crece con el tiempo
    t = (v["fecha"] - pd.Timestamp(FECHA_INICIO)).dt.days.to_numpy() / 638
    provincia = (v["ciudad"] != "Lima") & (v["ciudad"] != "Callao")
    p_efectivo = 0.48 - 0.14 * t + 0.10 * provincia
    p_yape = 0.24 + 0.12 * t - 0.05 * provincia
    p_plin = 0.07 + 0.02 * t - 0.02 * provincia
    p_debito = np.full(n, 0.13)
    p_credito = 1 - (p_efectivo + p_yape + p_plin + p_debito)
    probs = np.column_stack([p_efectivo, p_yape, p_plin, p_debito, p_credito])
    acumulado = probs.cumsum(axis=1)
    u = rng.random(n)[:, None]
    v["medio_pago"] = np.array(MEDIOS_PAGO)[(u > acumulado).sum(axis=1)]

    # ~35% de los tickets se registran con la tarjeta de puntos
    con_cliente = rng.random(n) < 0.35
    v["id_cliente"] = pd.array(
        np.where(con_cliente, rng.integers(1, n_clientes + 1, n), 0), dtype="Int64"
    )
    v.loc[~con_cliente, "id_cliente"] = pd.NA

    v = v.sort_values("fecha_hora", ignore_index=True)
    v.insert(0, "id_venta", np.arange(1, n + 1))
    return v[["id_venta", "fecha_hora", "id_tienda", "id_cliente", "medio_pago"]]


def _tabla_detalle(ventas: pd.DataFrame, productos: pd.DataFrame, rng) -> pd.DataFrame:
    n_items = 1 + rng.poisson(1.9, len(ventas))
    id_venta = np.repeat(ventas["id_venta"].to_numpy(), n_items)
    fecha = np.repeat(ventas["fecha_hora"].to_numpy(), n_items)
    m = len(id_venta)

    peso = productos["popularidad"].to_numpy(dtype=float)
    idx = rng.choice(len(productos), m, p=peso / peso.sum())
    precio = productos["precio_lista"].to_numpy()[idx]
    # alza de precios en enero 2026
    precio = np.where(fecha >= np.datetime64("2026-01-01"), precio * 1.045, precio)

    cantidad = rng.choice([1, 2, 3, 4, 6], m, p=[0.68, 0.19, 0.07, 0.04, 0.02])
    descuento = np.where(rng.random(m) < 0.08, rng.choice([0.10, 0.15, 0.20], m), 0.0)

    d = pd.DataFrame({
        "id_venta": id_venta,
        "id_producto": productos["id_producto"].to_numpy()[idx],
        "cantidad": cantidad,
        "precio_unitario": np.round(precio, 2),
        "descuento_pct": descuento,
    })
    # un mismo producto no se repite en la misma boleta: se suman las cantidades
    d = (d.groupby(["id_venta", "id_producto"], as_index=False)
           .agg(cantidad=("cantidad", "sum"),
                precio_unitario=("precio_unitario", "first"),
                descuento_pct=("descuento_pct", "max")))
    d["importe"] = (d["cantidad"] * d["precio_unitario"] * (1 - d["descuento_pct"])).round(2)
    return d


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------

COMENTARIOS = {
    "tiendas": (
        "Locales de la cadena. Una fila por tienda.",
        {
            "formato": "'Estándar' (local grande) o 'Express' (local chico de paso)",
            "ciudad": "Lima, Callao o ciudad de provincia",
            "fecha_apertura": "Fecha en que la tienda empezó a vender",
        },
    ),
    "categorias": ("Categorías de producto.", {}),
    "productos": (
        "Catálogo de productos.",
        {
            "precio_lista": "Precio de venta 2025 en soles, sin descuentos",
            "costo_unitario": "Costo de compra al proveedor en soles",
        },
    ),
    "clientes": (
        "Clientes inscritos en el programa de puntos.",
        {"segmento": "'Frecuente', 'Ocasional' o 'Nuevo'"},
    ),
    "ventas": (
        "Cabecera de cada boleta. Una fila por ticket de caja.",
        {
            "fecha_hora": "Fecha y hora de la venta (hora de Lima)",
            "id_cliente": "NULL cuando el cliente no usó su tarjeta de puntos",
            "medio_pago": "Efectivo, Yape, Plin, Tarjeta de débito o Tarjeta de crédito",
        },
    ),
    "detalle_venta": (
        "Líneas de cada boleta. Una fila por producto vendido en un ticket.",
        {
            "precio_unitario": "Precio cobrado por unidad en soles, antes del descuento",
            "descuento_pct": "Descuento aplicado a la línea (0.10 = 10%)",
            "importe": "Monto final de la línea en soles = cantidad * precio_unitario * (1 - descuento_pct)",
        },
    ),
}


def generar(ruta: Path = RUTA_DEFECTO, escala: float = 1.0, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    ruta = Path(ruta)
    ruta.unlink(missing_ok=True)

    tiendas = _tabla_tiendas()
    categorias, margenes = _tabla_categorias()
    productos = _tabla_productos(categorias, margenes, rng)
    n_clientes = max(200, int(6000 * escala))
    clientes = _tabla_clientes(n_clientes, tiendas, rng)
    ventas = _tabla_ventas(tiendas, n_clientes, escala, rng)
    detalle = _tabla_detalle(ventas, productos, rng)

    productos = productos[["id_producto", "nombre", "id_categoria",
                           "precio_lista", "costo_unitario"]]

    con = duckdb.connect(str(ruta))
    con.execute("""
        CREATE TABLE tiendas (
            id_tienda INTEGER PRIMARY KEY, nombre VARCHAR, distrito VARCHAR,
            ciudad VARCHAR, formato VARCHAR, fecha_apertura DATE);
        CREATE TABLE categorias (id_categoria INTEGER PRIMARY KEY, nombre VARCHAR);
        CREATE TABLE productos (
            id_producto INTEGER PRIMARY KEY, nombre VARCHAR,
            id_categoria INTEGER REFERENCES categorias(id_categoria),
            precio_lista DECIMAL(10,2), costo_unitario DECIMAL(10,2));
        CREATE TABLE clientes (
            id_cliente INTEGER PRIMARY KEY, nombre_completo VARCHAR,
            distrito VARCHAR, fecha_registro DATE, segmento VARCHAR);
        CREATE TABLE ventas (
            id_venta BIGINT PRIMARY KEY, fecha_hora TIMESTAMP,
            id_tienda INTEGER REFERENCES tiendas(id_tienda),
            id_cliente INTEGER REFERENCES clientes(id_cliente),
            medio_pago VARCHAR);
        CREATE TABLE detalle_venta (
            id_venta BIGINT REFERENCES ventas(id_venta),
            id_producto INTEGER REFERENCES productos(id_producto),
            cantidad INTEGER, precio_unitario DECIMAL(10,2),
            descuento_pct DECIMAL(4,2), importe DECIMAL(12,2));
    """)
    for nombre, df in [("tiendas", tiendas), ("categorias", categorias),
                       ("productos", productos), ("clientes", clientes),
                       ("ventas", ventas), ("detalle_venta", detalle)]:
        con.register("df_tmp", df)
        con.execute(f"INSERT INTO {nombre} SELECT * FROM df_tmp")
        con.unregister("df_tmp")

    for tabla, (desc, cols) in COMENTARIOS.items():
        con.execute(f"COMMENT ON TABLE {tabla} IS '{desc}'")
        for col, txt in cols.items():
            txt = txt.replace("'", "''")
            con.execute(f"COMMENT ON COLUMN {tabla}.{col} IS '{txt}'")
    con.close()
    return ruta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ruta", type=Path, default=RUTA_DEFECTO)
    parser.add_argument("--escala", type=float, default=1.0,
                        help="1.0 = volumen real; 0.05 sirve para pruebas rápidas")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    ruta = generar(args.ruta, args.escala, args.seed)
    con = duckdb.connect(str(ruta), read_only=True)
    print(f"Base creada en {ruta}")
    for t in ["tiendas", "categorias", "productos", "clientes", "ventas", "detalle_venta"]:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<15} {n:>10,} filas")
    con.close()


if __name__ == "__main__":
    main()
