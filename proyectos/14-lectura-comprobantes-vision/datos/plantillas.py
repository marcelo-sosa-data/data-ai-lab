"""
Dibuja la representación impresa de cada comprobante y la degrada como
llega en la práctica: escaneada, fotografiada con el celular o impresa a PDF.

Hay cuatro plantillas, que imitan lo que se ve en las cuentas por pagar de
una distribuidora: el formato de un sistema de facturación comercial, uno
más "moderno" con bandas de color, el formato de SEE-SOL (el emisor gratuito
de SUNAT, serie E001) y el ticket de impresora térmica.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANDIDATAS = {
    "sans": ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf"],
    "sans_b": ["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "cond": ["DejaVuSansCondensed.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
             "/usr/share/fonts/truetype/freefont/FreeSans.ttf"],
    "serif": ["DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
              "C:/Windows/Fonts/times.ttf"],
    "mono": ["DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "C:/Windows/Fonts/consola.ttf"],
    "mono_b": ["DejaVuSansMono-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
               "C:/Windows/Fonts/consolab.ttf"],
}
_cache: dict = {}


def fuente(tipo: str, tam: int):
    clave = (tipo, tam)
    if clave not in _cache:
        for ruta in CANDIDATAS[tipo]:
            try:
                _cache[clave] = ImageFont.truetype(ruta, tam)
                break
            except OSError:
                continue
        else:  # pragma: no cover - entorno sin ninguna fuente TrueType
            _cache[clave] = ImageFont.load_default(size=tam)
    return _cache[clave]


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "setiembre", "octubre", "noviembre", "diciembre"]


def fmt_monto(x: float, miles: bool = True) -> str:
    return f"{x:,.2f}" if miles else f"{x:.2f}"


def fmt_fecha(d, formato: str) -> str:
    if formato == "dmy":
        return d.strftime("%d/%m/%Y")
    if formato == "iso":
        return d.isoformat()
    if formato == "guion":
        return d.strftime("%d-%m-%Y")
    return f"{d.day:02d} de {MESES[d.month - 1]} de {d.year}"


def fmt_numero(serie: str, numero: int, ceros: bool) -> str:
    return f"{serie}-{numero:08d}" if ceros else f"{serie}-{numero}"


UNIDADES = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ",
            "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO",
            "DIECINUEVE", "VEINTE", "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO",
            "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
DECENAS = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
            "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _menor_mil(n: int) -> str:
    if n == 100:
        return "CIEN"
    c, r = divmod(n, 100)
    partes = [CENTENAS[c]] if c else []
    if r < 30:
        partes.append(UNIDADES[r])
    else:
        d, u = divmod(r, 10)
        partes.append(DECENAS[d] + (f" Y {UNIDADES[u]}" if u else ""))
    return " ".join(p for p in partes if p)


def en_letras(x: float, moneda: str) -> str:
    """Importe en letras como lo imprimen los sistemas de facturación."""
    entero, cent = int(x), round((x - int(x)) * 100)
    if entero == 0:
        texto = "CERO"
    else:
        miles, resto = divmod(entero, 1000)
        partes = []
        if miles:
            partes.append("MIL" if miles == 1 else f"{_menor_mil(miles)} MIL")
        if resto:
            partes.append(_menor_mil(resto))
        texto = " ".join(partes)
    nombre = "SOLES" if moneda == "PEN" else "DÓLARES AMERICANOS"
    return f"SON: {texto} CON {cent:02d}/100 {nombre}"


def _simbolo(moneda: str) -> str:
    return "S/" if moneda == "PEN" else "US$"


def _nombre_moneda(moneda: str) -> str:
    return "SOLES" if moneda == "PEN" else "DÓLARES AMERICANOS"


def _titulo(doc: dict) -> str:
    return "FACTURA ELECTRÓNICA" if doc["tipo"] == "factura" else "BOLETA DE VENTA ELECTRÓNICA"


def _texto_der(d: ImageDraw.ImageDraw, x_der: int, y: int, texto: str, f) -> None:
    d.text((x_der - d.textlength(texto, font=f), y), texto, font=f, fill=0)


def _logo(d: ImageDraw.ImageDraw, x: int, y: int, semilla: int) -> None:
    """Un isotipo genérico: el rectángulo o círculo que suele ir a la izquierda."""
    if semilla % 3 == 0:
        d.ellipse([x, y, x + 90, y + 90], outline=60, width=6)
        d.ellipse([x + 25, y + 25, x + 65, y + 65], fill=110)
    elif semilla % 3 == 1:
        d.rectangle([x, y, x + 90, y + 90], fill=150)
        d.polygon([(x + 10, y + 80), (x + 45, y + 15), (x + 80, y + 80)], fill=255)
    else:
        for i in range(4):
            d.rectangle([x + i * 24, y + 90 - (i + 1) * 20, x + i * 24 + 16, y + 90], fill=90)


# --------------------------------------------------------------- plantillas A4

ANCHO, ALTO = 1240, 1754  # A4 a 150 ppp


def _tabla_items(d, doc, y, cols, f, fb, linea=True):
    """Dibuja la tabla de ítems; `cols` = [(titulo, x, alineación, clave)]."""
    for titulo, x, al, _ in cols:
        (d.text((x, y), titulo, font=fb, fill=0) if al == "izq" else _texto_der(d, x, y, titulo, fb))
    y += 34
    if linea:
        d.line([(70, y), (ANCHO - 70, y)], fill=0, width=2)
    y += 12
    for it in doc["items"]:
        valores = {"cant": f"{it['cantidad']:g}", "uni": it["unidad"], "desc": it["descripcion"],
                   "vu": fmt_monto(it["valor_unitario"]), "imp": fmt_monto(it["importe"])}
        for _, x, al, clave in cols:
            v = valores[clave]
            (d.text((x, y), v, font=f, fill=0) if al == "izq" else _texto_der(d, x, y, v, f))
        y += 34
    return y


def plantilla_comercial(doc: dict) -> Image.Image:
    im = Image.new("L", (ANCHO, ALTO), 255)
    d = ImageDraw.Draw(im)
    f, fb, ft = fuente("sans", 21), fuente("sans_b", 21), fuente("sans", 19)
    _logo(d, 70, 70, doc["numero"])
    tam = 30
    while d.textlength(doc["razon_emisor"], font=fuente("sans_b", tam)) > 600 and tam > 18:
        tam -= 1
    d.text((180, 76), doc["razon_emisor"], font=fuente("sans_b", tam), fill=0)
    d.text((180, 116), doc["direccion_emisor"], font=ft, fill=0)
    d.text((180, 144), "Lima - Perú   Telf. " + doc["telefono_emisor"], font=ft, fill=0)
    # recuadro del RUC
    d.rectangle([800, 60, 1170, 240], outline=0, width=3)
    for i, txt in enumerate([f"R.U.C. {doc['ruc_emisor']}", _titulo(doc),
                             fmt_numero(doc["serie"], doc["numero"], doc["ceros"])]):
        fnt = fuente("sans_b", 25 if i != 1 else 21)
        w = d.textlength(txt, font=fnt)
        d.text((985 - w / 2, 88 + i * 50), txt, font=fnt, fill=0)

    y = 300
    filas = [("Fecha de emisión", fmt_fecha(doc["fecha_emision"], doc["formato_fecha"])),
             ("Señor(es)", doc["razon_receptor"])]
    if doc["ruc_receptor"]:
        filas.append(("RUC", doc["ruc_receptor"]))
    filas += [("Dirección", doc["direccion_receptor"]),
              ("Moneda", _nombre_moneda(doc["moneda"])),
              ("Condición de pago", doc["condicion_pago"])]
    if doc["orden_compra"]:
        filas.append(("Orden de compra", doc["orden_compra"]))
    for etq, val in filas:
        d.text((70, y), etq, font=fb, fill=0)
        d.text((330, y), ": " + val, font=f, fill=0)
        y += 34
    y += 30
    cols = [("Cant.", 70, "izq", "cant"), ("Unidad", 170, "izq", "uni"),
            ("Descripción", 290, "izq", "desc"), ("V. Unit.", 990, "der", "vu"),
            ("Importe", ANCHO - 70, "der", "imp")]
    y = _tabla_items(d, doc, y, cols, f, fb)
    d.line([(70, y + 6), (ANCHO - 70, y + 6)], fill=0, width=2)
    y += 40
    d.text((70, y), en_letras(doc["total"], doc["moneda"]), font=ft, fill=0)
    y += 50
    s = _simbolo(doc["moneda"])
    for etq, val in [("Op. Gravada", doc["base_imponible"]), ("I.G.V. 18%", doc["igv"]),
                     ("Importe Total", doc["total"])]:
        d.text((760, y), etq, font=fb, fill=0)
        _texto_der(d, ANCHO - 70, y, f"{s} {fmt_monto(val)}", fb)
        y += 38
    d.text((70, ALTO - 130), "Representación impresa de la " + _titulo(doc).title() +
           ". Consulte en www.sunat.gob.pe", font=ft, fill=0)
    return im


def plantilla_moderna(doc: dict) -> Image.Image:
    im = Image.new("L", (ANCHO, ALTO), 255)
    d = ImageDraw.Draw(im)
    f, fb, ft = fuente("cond", 22), fuente("sans_b", 21), fuente("cond", 19)
    d.rectangle([0, 0, ANCHO, 210], fill=215)
    _logo(d, 70, 60, doc["numero"] + 1)
    d.text((185, 62), doc["razon_emisor"].upper(), font=fuente("sans_b", 28), fill=20)
    d.text((185, 104), doc["direccion_emisor"], font=ft, fill=30)
    d.text((185, 132), "RUC " + doc["ruc_emisor"], font=fuente("sans_b", 22), fill=20)
    _texto_der(d, ANCHO - 70, 62, _titulo(doc), fuente("sans_b", 24))
    _texto_der(d, ANCHO - 70, 104, "N° " + fmt_numero(doc["serie"], doc["numero"], doc["ceros"]),
               fuente("sans_b", 30))

    y = 260
    izq = [("CLIENTE", doc["razon_receptor"]), ("RUC CLIENTE", doc["ruc_receptor"] or "-"),
           ("DIRECCIÓN", doc["direccion_receptor"])]
    der = [("F. EMISIÓN", fmt_fecha(doc["fecha_emision"], doc["formato_fecha"])),
           ("MONEDA", _nombre_moneda(doc["moneda"])), ("FORMA DE PAGO", doc["condicion_pago"]),
           ("O/C", doc["orden_compra"] or "-")]
    for i, (etq, val) in enumerate(izq):
        d.text((70, y + i * 62), etq, font=fuente("sans_b", 16), fill=80)
        d.text((70, y + i * 62 + 22), val, font=f, fill=0)
    for i, (etq, val) in enumerate(der):
        d.text((760, y + i * 62), etq, font=fuente("sans_b", 16), fill=80)
        d.text((760, y + i * 62 + 22), val, font=f, fill=0)
    y += 4 * 62 + 30
    d.rectangle([70, y - 6, ANCHO - 70, y + 34], fill=60)
    cols = [("CÓDIGO", 82, "izq", "uni"), ("DESCRIPCIÓN", 230, "izq", "desc"),
            ("CANT.", 880, "der", "cant"), ("P. UNIT.", 1030, "der", "vu"),
            ("SUBTOTAL", ANCHO - 82, "der", "imp")]
    for titulo, x, al, _ in cols:
        fnt = fuente("sans_b", 18)
        (d.text((x, y), titulo, font=fnt, fill=255) if al == "izq" else
         d.text((x - d.textlength(titulo, font=fnt), y), titulo, font=fnt, fill=255))
    y += 50
    for i, it in enumerate(doc["items"]):
        if i % 2:
            d.rectangle([70, y - 4, ANCHO - 70, y + 30], fill=238)
        d.text((82, y), it["codigo"], font=f, fill=0)
        d.text((230, y), it["descripcion"], font=f, fill=0)
        _texto_der(d, 880, y, f"{it['cantidad']:g}", f)
        _texto_der(d, 1030, y, fmt_monto(it["valor_unitario"]), f)
        _texto_der(d, ANCHO - 82, y, fmt_monto(it["importe"]), f)
        y += 36
    y += 40
    s = _simbolo(doc["moneda"])
    for etq, val, negrita in [("Sub Total", doc["base_imponible"], False),
                              ("I.G.V. (18%)", doc["igv"], False),
                              ("TOTAL A PAGAR", doc["total"], True)]:
        fnt = fuente("sans_b", 26) if negrita else f
        d.text((700, y), etq, font=fnt, fill=0)
        _texto_der(d, ANCHO - 82, y, f"{s} {fmt_monto(val)}", fnt)
        y += 44
    d.text((70, y + 30), en_letras(doc["total"], doc["moneda"]), font=ft, fill=40)
    d.rectangle([0, ALTO - 80, ANCHO, ALTO], fill=215)
    d.text((70, ALTO - 58), "Autorizado mediante Resolución de Intendencia N° 034-005-0005315/SUNAT",
           font=ft, fill=30)
    return im


def plantilla_see_sol(doc: dict) -> Image.Image:
    """Formato del Sistema de Emisión Electrónica de SUNAT: sobrio, en serif."""
    im = Image.new("L", (ANCHO, ALTO), 255)
    d = ImageDraw.Draw(im)
    f, fb = fuente("serif", 20), fuente("sans_b", 20)
    d.rectangle([60, 60, ANCHO - 60, 250], outline=0, width=2)
    d.text((90, 85), doc["razon_emisor"].upper(), font=fuente("sans_b", 24), fill=0)
    d.text((90, 125), doc["direccion_emisor"].upper(), font=f, fill=0)
    d.text((820, 85), _titulo(doc), font=fb, fill=0)
    d.text((820, 125), "RUC: " + doc["ruc_emisor"], font=fb, fill=0)
    d.text((820, 165), fmt_numero(doc["serie"], doc["numero"], doc["ceros"]), font=fb, fill=0)

    y = 290
    filas = [("Fecha de Emisión", fmt_fecha(doc["fecha_emision"], doc["formato_fecha"])),
             ("Señor(es)", doc["razon_receptor"].upper()),
             ("RUC", doc["ruc_receptor"] or "-"),
             ("Tipo de Moneda", _nombre_moneda(doc["moneda"])),
             ("Forma de pago", doc["condicion_pago"]),
             ("Observación", doc["orden_compra"] or "")]
    for etq, val in filas:
        d.text((80, y), etq, font=fb, fill=0)
        d.text((330, y), ": " + val, font=f, fill=0)
        y += 32
    y += 30
    d.rectangle([60, y - 8, ANCHO - 60, y + 30], outline=0, width=1)
    cols = [("Cantidad", 75, "izq", "cant"), ("Unidad Medida", 200, "izq", "uni"),
            ("Descripción", 380, "izq", "desc"), ("Valor Unitario", ANCHO - 80, "der", "vu")]
    y = _tabla_items(d, doc, y, cols, f, fb, linea=False)
    y += 50
    s = _simbolo(doc["moneda"])
    for etq, val in [("Sub Total Ventas", doc["base_imponible"]), ("Anticipos", 0.0),
                     ("Descuentos", 0.0), ("Valor Venta", doc["base_imponible"]),
                     ("ISC", 0.0), ("IGV", doc["igv"]), ("Otros Cargos", 0.0),
                     ("Importe Total", doc["total"])]:
        d.text((700, y), etq, font=fb, fill=0)
        _texto_der(d, ANCHO - 80, y, f"{s} {fmt_monto(val)}", f)
        y += 32
    d.text((80, y + 40), en_letras(doc["total"], doc["moneda"]).replace("SON: ", "SON: "), font=f, fill=0)
    return im


def plantilla_ticket(doc: dict) -> Image.Image:
    """Ticket de impresora térmica de 80 mm. Lo usan ferreterías, grifos y bodegas."""
    ancho = 600
    f, fb = fuente("mono", 21), fuente("mono_b", 22)
    lineas: list[tuple[str, object, str]] = []  # (texto, fuente, alineación)

    def c(t, fnt=f):
        lineas.append((t, fnt, "centro"))

    def i(t, fnt=f):
        lineas.append((t, fnt, "izq"))

    c(doc["razon_emisor"].upper()[:38], fb)
    c(doc["direccion_emisor"][:42])
    c("RUC: " + doc["ruc_emisor"], fb)
    c("-" * 42)
    c(_titulo(doc), fb)
    c(fmt_numero(doc["serie"], doc["numero"], doc["ceros"]), fb)
    c("-" * 42)
    i("FECHA: " + fmt_fecha(doc["fecha_emision"], doc["formato_fecha"]) + "  " + doc["hora"])
    i("CLIENTE: " + doc["razon_receptor"].upper()[:33])
    if doc["ruc_receptor"]:
        i("RUC: " + doc["ruc_receptor"])
    i("MONEDA: " + _nombre_moneda(doc["moneda"]))
    if doc["orden_compra"]:
        i("O.C.: " + doc["orden_compra"])
    c("-" * 42)
    for it in doc["items"]:
        i(it["descripcion"][:42])
        izq = f"  {it['cantidad']:g} x {fmt_monto(it['valor_unitario'], False)}"
        der = fmt_monto(it["importe"])
        i(izq + " " * max(1, 42 - len(izq) - len(der)) + der)
    c("-" * 42)
    s = _simbolo(doc["moneda"])
    for etq, val in [("OP. GRAVADA", doc["base_imponible"]), ("IGV 18%", doc["igv"]),
                     ("TOTAL", doc["total"])]:
        der = f"{s} {fmt_monto(val)}"
        i(etq + " " * max(1, 42 - len(etq) - len(der)) + der, fb if etq == "TOTAL" else f)
    c("-" * 42)
    letras = en_letras(doc["total"], doc["moneda"]).split()
    renglon = ""
    for palabra in letras:
        if len(renglon) + len(palabra) + 1 > 40:
            c(renglon)
            renglon = palabra
        else:
            renglon = f"{renglon} {palabra}".strip()
    c(renglon)
    c("GRACIAS POR SU COMPRA")

    alto = 60 + 32 * len(lineas) + 60
    im = Image.new("L", (ancho, alto), 255)
    d = ImageDraw.Draw(im)
    y = 50
    for t, fnt, al in lineas:
        x = (ancho - d.textlength(t, font=fnt)) / 2 if al == "centro" else 24
        d.text((x, y), t, font=fnt, fill=0)
        y += 32
    return im


PLANTILLAS = {"comercial": plantilla_comercial, "moderna": plantilla_moderna,
              "see_sol": plantilla_see_sol, "ticket": plantilla_ticket}


# --------------------------------------------------------------- degradación

def degradar(im: Image.Image, captura: str, rng: np.random.Generator) -> Image.Image:
    """
    Simula cómo llega el archivo. `pdf`: impreso a imagen, limpio.
    `escaneo`: leve giro, ruido y compresión. `foto`: giro mayor, sombra,
    desenfoque, menos resolución y fondo de mesa alrededor.
    """
    if captura == "pdf":
        return im.convert("RGB")

    if captura == "escaneo":
        angulo = rng.uniform(-1.5, 1.5)
        im = im.rotate(angulo, resample=Image.BICUBIC, expand=True, fillcolor=245)
        arr = np.asarray(im, dtype=np.float32)
        arr = arr * rng.uniform(0.88, 0.97) + rng.uniform(5, 20)
        arr += rng.normal(0, rng.uniform(4, 10), arr.shape)
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        if rng.random() < 0.5:
            im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
        return _comprimir(im.convert("RGB"), int(rng.integers(55, 85)))

    # foto con el celular
    escala = rng.uniform(0.62, 0.85)
    im = im.resize((int(im.width * escala), int(im.height * escala)), Image.LANCZOS)
    margen = int(im.width * 0.08)
    fondo = Image.new("L", (im.width + 2 * margen, im.height + 2 * margen), int(rng.integers(70, 140)))
    fondo.paste(im, (margen, margen))
    im = fondo.rotate(rng.uniform(-4, 4), resample=Image.BICUBIC, expand=False,
                      fillcolor=int(rng.integers(70, 140)))
    arr = np.asarray(im, dtype=np.float32)
    h, w = arr.shape
    # sombra: gradiente desde una esquina
    yy, xx = np.mgrid[0:h, 0:w]
    ang = rng.uniform(0, 2 * np.pi)
    grad = (np.cos(ang) * xx / w + np.sin(ang) * yy / h)
    grad = (grad - grad.min()) / (np.ptp(grad) + 1e-9)
    arr = arr * (1 - rng.uniform(0.15, 0.40) * grad)
    arr += rng.normal(0, rng.uniform(6, 12), arr.shape)
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.2)))
    tinte = Image.merge("RGB", [im.point(lambda v: min(255, v + 6)), im, im.point(lambda v: max(0, v - 8))])
    return _comprimir(tinte, int(rng.integers(45, 72)))


def _comprimir(im: Image.Image, calidad: int) -> Image.Image:
    from io import BytesIO

    buf = BytesIO()
    im.save(buf, "JPEG", quality=calidad)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def dibujar(doc: dict, captura: str, rng: np.random.Generator, destino: Path) -> Path:
    im = degradar(PLANTILLAS[doc["plantilla"]](doc), captura, rng)
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino, "JPEG", quality=92)
    return destino
