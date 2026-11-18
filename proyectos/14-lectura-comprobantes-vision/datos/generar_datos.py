"""
Genera los comprobantes de compra sin XML que recibió Comercial Tayta en
setiembre y octubre de 2026: proveedores con su padrón de SUNAT, órdenes de
compra, la imagen de cada comprobante tal como llegó y la verdad de cada
campo (aux_verdad), que el extractor no ve.

    python datos/generar_datos.py              # ~1,000 comprobantes
    python datos/generar_datos.py --escala 0.1

Los errores de los proveedores se siembran a propósito (IGV mal calculado,
total que no cuadra, factura a otro RUC, monto sobre la OC, proveedor no
habido, reenvíos duplicados) y quedan marcados en aux_verdad.anomalia.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent / "src"))

from plantillas import dibujar  # noqa: E402

from comprobantes.reglas import digito_ruc  # noqa: E402

INICIO, FIN = date(2026, 9, 1), date(2026, 10, 31)
EMPRESA = {"ruc": None, "razon": "COMERCIAL TAYTA S.A.C.",
           "direccion": "Av. Industrial 1450, Independencia - Lima"}

PREFIJOS = ["Distribuidora", "Inversiones", "Corporación", "Industrias", "Comercializadora",
            "Agroindustrias", "Importaciones", "Molinera", "Envases y Embalajes", "Negociaciones",
            "Productos Alimenticios", "Grupo"]
NOMBRES = ["San Gabriel", "Los Olivos del Norte", "Huáscar", "Santa Rosa de Carabayllo", "Pukara",
           "El Trigal", "Kusi", "Mayu", "Ccoyllur", "Valle del Chillón", "La Perla Andina", "Sumaq",
           "Inti Raymi", "Ñawpa", "Puquio", "Cerro Azul", "Altomayo", "Wayra", "Chaska", "Illari",
           "Villa Rica", "Tres Cruces", "El Molino de Oro", "Santa Clotilde", "Miski", "Allin Mikuy",
           "Pachamanca", "Huaral Fresh", "Nevado Blanco", "Río Santa", "Collique", "Cantagallo",
           "Los Andes del Rímac", "Punta Negra", "Ayllu", "Chancay Norte", "Kallpa", "Tambo Real",
           "Qori Sara", "San Martín de Porres", "Puerto Viejo", "La Esperanza", "Nueva Era",
           "Lurín Valle", "Vista Alegre", "Huaycán", "Las Lomas", "Señor de Muruhuay"]
SUFIJOS = ["S.A.C.", "S.A.C.", "S.A.C.", "E.I.R.L.", "S.A.", "S.R.L."]
PERSONAS = ["Quispe Mamani Rosa Elvira", "Huamán Torres Juan Carlos", "Flores Ccahuana Marleni",
            "Rojas Paucar Edwin", "Condori Apaza Luz Marina", "Chávez Ríos Wilmer", "Mendoza Saavedra Gladys",
            "Ramos Huanca Percy", "Vargas Llanos Nelly", "Castillo Yupanqui Hernán", "Salazar Inga Doris",
            "Ticona Larico Félix", "Aguilar Poma Yesenia", "Cárdenas Nina Óscar", "Paredes Soto Maribel"]
VIAS = ["Av. Los Próceres", "Jr. Huancavelica", "Av. Naranjal", "Calle Los Tornos", "Av. Argentina",
        "Jr. Ica", "Av. Separadora Industrial", "Calle Las Fraguas", "Av. Nicolás Ayllón", "Av. Canta Callao"]
DISTRITOS = ["Ate", "Cercado de Lima", "Los Olivos", "Callao", "San Juan de Lurigancho",
             "Puente Piedra", "Lurín", "Villa El Salvador", "Comas", "Chorrillos"]

CATALOGO = {
    "abarrotes": [("Arroz extra costal 50 kg", "SAC", 168.0), ("Azúcar rubia costal 50 kg", "SAC", 152.0),
                  ("Aceite vegetal caja 12x1 L", "CJA", 96.5), ("Fideo spaghetti caja 20x500 g", "CJA", 41.8),
                  ("Leche evaporada caja 48x400 g", "CJA", 148.0), ("Atún en trozos caja 48x170 g", "CJA", 172.0),
                  ("Avena en hojuelas caja 24x900 g", "CJA", 118.0), ("Lentejas saco 25 kg", "SAC", 121.0),
                  ("Harina sin preparar saco 50 kg", "SAC", 139.0), ("Sal yodada fardo 25x1 kg", "FDO", 27.5)],
    "bebidas": [("Gaseosa 3 L pack x4", "PAQ", 22.4), ("Agua sin gas 625 ml paq x15", "PAQ", 13.9),
                ("Bebida rehidratante 500 ml paq x12", "PAQ", 26.0), ("Néctar de durazno 1 L caja x12", "CJA", 38.5),
                ("Cerveza lata 355 ml caja x24", "CJA", 62.0), ("Agua de mesa bidón 20 L", "UND", 8.9)],
    "limpieza": [("Detergente en polvo 4 kg", "BOL", 29.9), ("Lejía 4 L caja x4", "CJA", 24.6),
                 ("Papel higiénico 40 rollos", "PAQ", 33.0), ("Jabón de lavar caja x50", "CJA", 71.0),
                 ("Desinfectante 3.8 L", "GLN", 15.4)],
    "envases": [("Stretch film 18\" x 500 m", "ROL", 34.0), ("Caja cartón doble corrugado", "MIL", 1180.0),
                ("Bolsa polietileno 20x30 millar", "MIL", 96.0), ("Parihuela de madera 1.20 x 1.00", "UND", 32.0)],
    "servicios": [("Servicio de transporte de carga Lima - Huaral", "ZZ", 950.0),
                  ("Servicio de estiba y desestiba", "ZZ", 420.0),
                  ("Mantenimiento preventivo de montacargas", "ZZ", 1350.0),
                  ("Alquiler de almacén mes", "ZZ", 6800.0),
                  ("Servicio de fumigación de almacén", "ZZ", 780.0)],
    "ferreteria": [("Candado de bronce 50 mm", "UND", 24.5), ("Cinta de embalaje 2\" x 100 yd", "UND", 3.9),
                   ("Guantes de nitrilo caja x100", "CJA", 18.0), ("Foco LED 18 W", "UND", 7.6),
                   ("Combustible diésel B5 galón", "GLN", 16.2)],
}
CONDICIONES = [("Contado", 0), ("Crédito 15 días", 15), ("Crédito 30 días", 30), ("Crédito 45 días", 45)]


def ruc(rng: np.random.Generator, prefijo: str) -> str:
    base = prefijo + "".join(str(d) for d in rng.integers(0, 10, 8))
    return base + str(digito_ruc(base))


def crear_proveedores(rng: np.random.Generator, n_empresas: int = 64, n_personas: int = 15) -> list[dict]:
    provs, usados = [], set()
    rubros_emp = ["abarrotes"] * 22 + ["bebidas"] * 14 + ["limpieza"] * 10 + ["envases"] * 8 + ["servicios"] * 10
    for i in range(n_empresas):
        while True:
            nombre = f"{rng.choice(PREFIJOS)} {rng.choice(NOMBRES)} {rng.choice(SUFIJOS)}"
            if nombre not in usados:
                usados.add(nombre)
                break
        rubro = rubros_emp[i % len(rubros_emp)]
        grande = rng.random() < 0.45
        provs.append({
            "ruc": ruc(rng, "20"), "razon_social": nombre, "rubro": rubro, "tamano": "grande" if grande else "mediano",
            "plantilla": rng.choice(["comercial", "moderna"], p=[0.55, 0.45]) if grande else
                         rng.choice(["comercial", "moderna", "see_sol", "ticket"], p=[0.35, 0.25, 0.25, 0.15]),
            "serie": rng.choice(["F001", "F001", "F002", "F003", "FA01"]),
            "peso": float(rng.lognormal(1.0 if grande else 0.2, 0.6)),
        })
    for nombre in PERSONAS[:n_personas]:
        provs.append({
            "ruc": ruc(rng, "10"), "razon_social": nombre.upper(), "rubro": rng.choice(["ferreteria", "abarrotes", "limpieza"]),
            "tamano": "pequeno", "plantilla": rng.choice(["see_sol", "ticket"], p=[0.45, 0.55]),
            "serie": "E001", "peso": float(rng.lognormal(-0.3, 0.5)),
        })
    for p in provs:
        p["direccion"] = f"{rng.choice(VIAS)} {int(rng.integers(100, 3999))}, {rng.choice(DISTRITOS)}"
        p["telefono"] = f"01 {int(rng.integers(200, 799))}-{int(rng.integers(1000, 9999))}"
        p["condicion_pago"] = CONDICIONES[int(rng.choice(4, p=[0.2, 0.25, 0.4, 0.15]))] if p["tamano"] != "pequeno" \
            else CONDICIONES[int(rng.choice(2, p=[0.7, 0.3]))]
        p["ceros"] = bool(rng.random() < 0.7)
        p["formato_fecha"] = rng.choice(["dmy", "dmy", "iso", "guion", "texto"]) if p["plantilla"] != "ticket" \
            else rng.choice(["dmy", "iso"])
        p["estado"], p["condicion"] = "ACTIVO", "HABIDO"
        p["correlativo"] = int(rng.integers(150, 40000))
    # tres proveedores medianos no habidos en todo el periodo (dejan de dar crédito fiscal)
    for p in rng.choice([p for p in provs if p["tamano"] == "mediano"], 3, replace=False):
        p["condicion"] = "NO HABIDO"
    return provs


def _captura(rng, tamano: str) -> str:
    p = {"grande": [0.25, 0.60, 0.15], "mediano": [0.10, 0.55, 0.35], "pequeno": [0.03, 0.37, 0.60]}[tamano]
    return str(rng.choice(["pdf", "escaneo", "foto"], p=p))


def crear_documento(rng, prov: dict, recepcion: date, doc_id: int) -> dict:
    tipo = "boleta" if prov["tamano"] == "pequeno" and rng.random() < 0.35 else "factura"
    serie = prov["serie"] if tipo == "factura" else ("EB01" if prov["serie"] == "E001" else "B001")
    if prov["plantilla"] == "ticket" and tipo == "factura" and prov["serie"].startswith("F"):
        serie = "F" + prov["serie"][1:]
    prov["correlativo"] += int(rng.integers(1, 30))
    emision = recepcion - timedelta(days=int(min(rng.geometric(0.45) - 1, 9)))
    moneda = "USD" if prov["rubro"] in ("envases", "servicios") and rng.random() < 0.25 else "PEN"
    catalogo = CATALOGO[prov["rubro"]]
    n_items = 1 if prov["rubro"] == "servicios" else int(min(rng.geometric(0.33), 8))
    items = []
    for k in rng.choice(len(catalogo), size=min(n_items, len(catalogo)), replace=False):
        desc, uni, precio = catalogo[int(k)]
        if prov["rubro"] == "servicios":
            cant = 1
        elif uni == "MIL":
            cant = int(rng.integers(1, 6))
        else:
            cant = int(rng.choice([1, 2, 3, 5, 6, 10, 12, 20, 24, 40, 50, 60, 100], p=[.06, .06, .05, .1, .06, .14, .08, .12, .07, .08, .08, .05, .05]))
        if prov["tamano"] == "pequeno":
            cant = max(1, cant // 5)
        vu = round(precio * rng.uniform(0.9, 1.12) / (3.75 if moneda == "USD" else 1), 2)
        items.append({"descripcion": desc, "unidad": uni, "codigo": f"{uni}{int(rng.integers(1000, 9999))}",
                      "cantidad": cant, "valor_unitario": vu, "importe": round(cant * vu, 2)})
    base = round(sum(i["importe"] for i in items), 2)
    igv = round(base * 0.18, 2)
    con_oc = tipo == "factura" and rng.random() < (0.92 if prov["rubro"] != "servicios" else 0.5)
    return {
        "doc_id": doc_id, "tipo": tipo, "ruc_emisor": prov["ruc"], "razon_emisor": prov["razon_social"],
        "direccion_emisor": prov["direccion"], "telefono_emisor": prov["telefono"],
        "ruc_receptor": EMPRESA["ruc"] if tipo == "factura" else None,
        "razon_receptor": EMPRESA["razon"] if tipo == "factura" or rng.random() < 0.5 else "CLIENTES VARIOS",
        "direccion_receptor": EMPRESA["direccion"],
        "serie": serie, "numero": prov["correlativo"], "fecha_emision": emision, "fecha_recepcion": recepcion,
        "hora": f"{int(rng.integers(7, 20)):02d}:{int(rng.integers(0, 60)):02d}",
        "moneda": moneda, "items": items, "base_imponible": base, "igv": igv, "total": round(base + igv, 2),
        "orden_compra": None, "con_oc": con_oc,
        "condicion_pago": prov["condicion_pago"][0], "dias_credito": prov["condicion_pago"][1],
        "plantilla": prov["plantilla"], "ceros": prov["ceros"], "formato_fecha": prov["formato_fecha"],
        "captura": _captura(rng, prov["tamano"]), "anomalia": None, "duplicado_de": None,
    }


def sembrar_anomalia(rng, doc: dict, otros_rucs: list[str]) -> None:
    """Cambia el documento según el error que comete el proveedor."""
    u = rng.random()
    if doc["tipo"] == "factura" and u < 0.02:
        doc["anomalia"] = "receptor_errado"
        doc["ruc_receptor"] = str(rng.choice(otros_rucs))
        doc["razon_receptor"] = str(rng.choice(["INVERSIONES TAYTA E.I.R.L.", "COMERCIAL TAYPE S.A.C.",
                                                 "DISTRIBUIDORA TAYTA NORTE S.A.C."]))
    elif u < 0.045:
        doc["anomalia"] = "igv_mal"
        modo = rng.choice(["sobre_total", "redondeo", "tasa"])
        if modo == "sobre_total":     # calculan el 18% sobre lo que debía ser el total
            doc["igv"] = round(doc["base_imponible"] * 1.18 * 0.18, 2)
        elif modo == "redondeo":      # suman IGV ítem por ítem truncado y se va lejos
            doc["igv"] = round(doc["igv"] + float(rng.choice([-1, 1])) * rng.uniform(0.6, 12), 2)
        else:                         # usan la tasa del restaurante MYPE (10.5%)
            doc["igv"] = round(doc["base_imponible"] * 0.105, 2)
        doc["total"] = round(doc["base_imponible"] + doc["igv"], 2)
    elif u < 0.057:
        doc["anomalia"] = "total_mal"
        doc["total"] = round(doc["total"] + rng.choice([1, -1]) * rng.uniform(5, 80), 2)
    elif doc["con_oc"] and u < 0.105:
        doc["anomalia"] = "excede_oc"


def generar(ruta_db: Path, escala: float = 1.0, seed: int = 14, imagenes: bool = True) -> Path:
    rng = np.random.default_rng(seed)
    EMPRESA["ruc"] = ruc(np.random.default_rng(seed + 1), "20")
    provs = crear_proveedores(rng)
    otros = [ruc(rng, "20") for _ in range(3)]
    pesos = np.array([p["peso"] for p in provs])
    pesos /= pesos.sum()

    dias = [INICIO + timedelta(days=i) for i in range((FIN - INICIO).days + 1)]
    docs, n = [], 0
    for d in dias:
        if d.weekday() == 6:
            continue
        lam = (19 if d.weekday() < 5 else 7) * escala * (1.25 if d.day <= 5 or d.day >= 26 else 1.0)
        for _ in range(int(rng.poisson(lam))):
            n += 1
            prov = provs[int(rng.choice(len(provs), p=pesos))]
            doc = crear_documento(rng, prov, d, n)
            sembrar_anomalia(rng, doc, otros)
            if prov["condicion"] != "HABIDO" and doc["anomalia"] is None:
                doc["anomalia"] = "no_habido"
            docs.append(doc)

    # reenvíos: el mismo comprobante llega otra vez por otro canal días después
    for orig in [docs[int(i)] for i in rng.choice(len(docs), size=int(len(docs) * 0.03), replace=False)]:
        d = orig["fecha_recepcion"] + timedelta(days=int(rng.integers(2, 15)))
        if d > FIN:
            continue
        n += 1
        prov = next(p for p in provs if p["ruc"] == orig["ruc_emisor"])
        dup = dict(orig, doc_id=n, fecha_recepcion=d, captura=_captura(rng, prov["tamano"]),
                   anomalia="duplicado", duplicado_de=orig["doc_id"])
        docs.append(dup)
    docs.sort(key=lambda x: (x["fecha_recepcion"], x["doc_id"]))

    # órdenes de compra: la OC normal queda igual o algo por encima del total
    ordenes, n_oc = {}, 1200
    for doc in docs:
        if doc["duplicado_de"] is not None:
            orig = next(x for x in docs if x["doc_id"] == doc["duplicado_de"])
            doc["orden_compra"] = orig["orden_compra"]
            continue
        if not doc["con_oc"]:
            continue
        n_oc += int(rng.integers(1, 4))
        oc = f"OC-2026-{n_oc:05d}"
        doc["orden_compra"] = oc
        factor = rng.uniform(1.03, 1.25) if doc["anomalia"] == "excede_oc" else -rng.uniform(0.0, 0.08)
        monto = doc["total"] / factor if factor > 0 else doc["total"] * (1 - factor)
        ordenes[oc] = {"orden_compra": oc, "ruc_proveedor": doc["ruc_emisor"], "moneda": doc["moneda"],
                       "monto": round(monto, 2), "fecha": doc["fecha_emision"] - timedelta(days=int(rng.integers(2, 20)))}

    carpeta = ruta_db.parent / "imagenes"
    filas = []
    for doc in docs:
        archivo = carpeta / f"{doc['doc_id']:05d}.jpg"
        if imagenes:
            dibujar(doc, doc["captura"], rng, archivo)
        vence = doc["fecha_emision"] + timedelta(days=doc["dias_credito"]) if doc["dias_credito"] \
            else doc["fecha_recepcion"] + timedelta(days=1)
        filas.append({**{k: doc[k] for k in ["doc_id", "tipo", "ruc_emisor", "ruc_receptor", "serie", "numero",
                                             "fecha_emision", "moneda", "base_imponible", "igv", "total",
                                             "orden_compra", "fecha_recepcion", "condicion_pago", "captura",
                                             "plantilla", "anomalia", "duplicado_de"]},
                      "razon_emisor": doc["razon_emisor"], "fecha_vencimiento": vence,
                      "n_items": len(doc["items"]), "items": json.dumps(doc["items"], ensure_ascii=False),
                      "archivo": archivo.name})

    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    if ruta_db.exists():
        ruta_db.unlink()
    import pandas as pd

    con = duckdb.connect(str(ruta_db))
    con.register("t_verdad", pd.DataFrame(filas))
    con.execute("CREATE TABLE aux_verdad AS SELECT * FROM t_verdad")
    con.execute("""CREATE TABLE recepcion AS SELECT doc_id, archivo, fecha_recepcion, captura,
                   CASE WHEN captura = 'foto' THEN 'whatsapp' WHEN captura = 'pdf' THEN 'correo'
                        ELSE 'mesa de partes' END AS canal FROM aux_verdad ORDER BY doc_id""")
    padron = pd.DataFrame([{k: p[k] for k in ["ruc", "razon_social", "rubro", "tamano", "estado", "condicion"]}
                           for p in provs])
    con.register("t_padron", padron)
    con.execute("CREATE TABLE padron AS SELECT * FROM t_padron")
    con.register("t_oc", pd.DataFrame(list(ordenes.values())))
    con.execute("CREATE TABLE ordenes_compra AS SELECT * FROM t_oc")
    con.execute("CREATE TABLE empresa AS SELECT ? AS ruc, ? AS razon_social", [EMPRESA["ruc"], EMPRESA["razon"]])
    con.close()
    return ruta_db


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--salida", type=Path, default=AQUI / "tayta.duckdb")
    a = ap.parse_args()
    ruta = generar(a.salida, a.escala, a.seed)
    con = duckdb.connect(str(ruta), read_only=True)
    print(con.sql("SELECT COUNT(*) AS comprobantes, COUNT(anomalia) AS con_anomalia FROM aux_verdad"))
    print(con.sql("SELECT anomalia, COUNT(*) n FROM aux_verdad GROUP BY 1 ORDER BY 2 DESC"))
    print(con.sql("SELECT captura, plantilla, COUNT(*) n FROM aux_verdad GROUP BY ALL ORDER BY ALL"))
