"""
Extractor sin LLM: Tesseract más un parser de reglas.

Es el modo demo (no necesita API key) y también la línea base contra la que
se compara un modelo de visión. Cada campo sale con una confianza, la menor
confianza de Tesseract entre las palabras de donde se leyó; eso es lo que
usa el ruteo para mandar a revisión una lectura dudosa.

El parser no calcula nada: si no encuentra el IGV no lo saca de total menos
base. Completar un campo con aritmética escondería justo los errores que las
validaciones tienen que ver.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from .esquema import Comprobante

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


@dataclass
class Lectura:
    comprobante: Comprobante
    confianza: dict[str, float] = field(default_factory=dict)   # 0 a 1 por campo
    texto: str = ""
    extractor: str = ""


# ------------------------------------------------------------- preprocesado

def preparar(im: Image.Image) -> Image.Image:
    """Recorta el papel si es una foto, endereza y lleva el texto a un tamaño legible."""
    import cv2

    g = np.asarray(im.convert("L"))
    # el papel es la región clara más grande; en un escaneo es casi toda la imagen
    _, mascara = cv2.threshold(cv2.GaussianBlur(g, (9, 9), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contornos:
        c = max(contornos, key=cv2.contourArea)
        if cv2.contourArea(c) > 0.3 * g.size:
            (cx, cy), (w, h), ang = cv2.minAreaRect(c)
            if w > h:  # minAreaRect cambia de convención según la versión de OpenCV
                w, h, ang = h, w, ang + 90
            while ang > 45:
                ang -= 90
            while ang < -45:
                ang += 90
            if abs(ang) > 0.3:
                M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
                g = cv2.warpAffine(g, M, (g.shape[1], g.shape[0]), flags=cv2.INTER_CUBIC, borderValue=255)
            x0, y0 = int(max(cx - w / 2, 0)), int(max(cy - h / 2, 0))
            g = g[y0:int(cy + h / 2), x0:int(cx + w / 2)]
    if g.shape[1] < 1100:
        f = 1300 / g.shape[1]
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    # aplana la sombra de las fotos dividiendo por el fondo estimado
    fondo = cv2.medianBlur(cv2.dilate(g, np.ones((7, 7), np.uint8)), 31)
    g = cv2.divide(g, fondo, scale=255)
    return Image.fromarray(g)


# ------------------------------------------------------------- utilidades de texto

def _plano(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.upper())
    return "".join(c for c in t if not unicodedata.combining(c))


RE_MONTO = re.compile(r"(\d{1,3}(?:[,.]\d{3})+[.,]\d{2}|\d+[.,]\d{2})(?!\d)")


def a_numero(s: str) -> float:
    s = s.strip()
    dec = s[-3]
    entero = re.sub(r"[.,]", "", s[:-3])
    return float(f"{entero}.{s[-2:]}") if dec in ".," else float(re.sub(r"[.,]", "", s))


def _digitos(t: str) -> str:
    """Corrige las confusiones típicas del OCR dentro de un número."""
    return t.translate(str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1",
                                      "|": "1", "S": "5", "B": "8", "Z": "2"}))


@dataclass
class Linea:
    texto: str
    palabras: list[tuple[str, float]]

    @property
    def plano(self) -> str:
        return _plano(self.texto)

    def confianza(self, valor: str) -> float:
        """Menor confianza entre las palabras que forman `valor`."""
        objetivo = re.sub(r"\W", "", valor.upper())
        confs = [c for p, c in self.palabras
                 if (w := re.sub(r"\W", "", p.upper())) and len(w) >= 2 and (w in objetivo or objetivo in _digitos(w))]
        if not confs:
            confs = [c for _, c in self.palabras] or [0.0]
        return min(confs) / 100


def _lineas(datos: dict) -> list[Linea]:
    grupos: dict[tuple, list] = {}
    arriba: dict[tuple, int] = {}
    for i, txt in enumerate(datos["text"]):
        if not txt.strip():
            continue
        clave = (datos["block_num"][i], datos["par_num"][i], datos["line_num"][i])
        grupos.setdefault(clave, []).append((datos["left"][i], txt, float(datos["conf"][i])))
        arriba[clave] = min(arriba.get(clave, 10**9), datos["top"][i])
    salida = []
    for clave in sorted(grupos, key=arriba.get):
        palabras = [(t, max(c, 0.0)) for _, t, c in sorted(grupos[clave])]
        salida.append(Linea(" ".join(p for p, _ in palabras), palabras))
    return salida


# ------------------------------------------------------------- parser

RE_SERIE = re.compile(r"\b([FBE8][A-Z0-9]{3,5})\s*[-–—~_]\s*(?:N\S{0,2}\s*)?([0-9OIDS]{1,8}(?: \d{1,4}\b)?)")
RE_FECHA = [
    (re.compile(r"\b(\d{2})[/](\d{2})[/](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2}) DE ([A-Z]+) DE (\d{4})\b"), "texto"),
]
RE_OC = re.compile(r"[O0Q]C\s*[-–]?\s*(\d{4})\s*[-–]\s*([0-9OIlS]{5})")
ETIQ_BASE = ("GRAVADA", "SUB TOTAL", "SUBTOTAL", "VALOR VENTA", "SUB BTAL", "SUB TAL")
ETIQ_TOTAL = ("IMPORTE TOTAL", "TOTAL A PAGAR", "TOTAL")
RE_IGV = re.compile(r"(?<![A-Z])[1IL|]?[G6][6C]?V(?![A-Z])")


def _serie(cand: str) -> str:
    """
    Arma la serie con la primera letra, la segunda posición y los dos últimos
    dígitos. Tesseract suele duplicar o mezclar el cero (FO001, FOO0O1), pero
    la segunda posición puede ser una letra de verdad (FA01, EB01).
    """
    cand = cand.upper()
    primero = {"8": "B"}.get(cand[0], cand[0])
    segundo = "0" if cand[1] in "OQD" else cand[1]
    return primero + segundo + _digitos(cand[-2:])


def _fecha(plano: str) -> date | None:
    for rx, fmt in RE_FECHA:
        m = rx.search(plano)
        if not m:
            continue
        try:
            if fmt == "iso":
                return date(int(m[1]), int(m[2]), int(m[3]))
            if fmt == "texto":
                mes = MESES.get(m[2].lower())
                return date(int(m[3]), mes, int(m[1])) if mes else None
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            continue
    return None


def parsear(lineas: list[Linea]) -> tuple[Comprobante, dict[str, float]]:
    c: dict = {}
    conf: dict[str, float] = {}
    todo = "\n".join(l.plano for l in lineas)

    palabras = set(re.findall(r"[A-Z]{5,}", todo))
    if "BOLETA" in todo:
        c["tipo"], conf["tipo"] = "boleta", 1.0
    elif "FACTURA" in todo:
        c["tipo"], conf["tipo"] = "factura", 1.0
    elif difflib.get_close_matches("FACTURA", palabras, cutoff=0.7):
        c["tipo"], conf["tipo"] = "factura", 0.7
    elif difflib.get_close_matches("BOLETA", palabras, cutoff=0.7):
        c["tipo"], conf["tipo"] = "boleta", 0.7

    rucs: list[tuple[str, Linea]] = []
    for l in lineas:
        compacto = re.sub(r"(?<=\d)[ .](?=\d)", "", _digitos_en_contexto(l.texto))
        for m in re.finditer(r"(?<!\d)((?:10|15|17|20)\d{9})(?!\d)", compacto):
            if m[1] not in [r for r, _ in rucs]:
                rucs.append((m[1], l))
    if rucs:
        c["ruc_emisor"], conf["ruc_emisor"] = rucs[0][0], rucs[0][1].confianza(rucs[0][0])
    if len(rucs) > 1:
        c["ruc_receptor"], conf["ruc_receptor"] = rucs[1][0], rucs[1][1].confianza(rucs[1][0])

    for l in lineas:
        m = RE_SERIE.search(l.texto.upper().replace(" - ", "-"))
        if m and not RE_OC.search(l.texto.upper()):
            c["serie"] = _serie(m[1])
            digitos = _digitos(m[2].replace(" ", ""))
            c["numero"] = int(digitos[-8:])
            conf["serie"] = conf["numero"] = l.confianza(m[0])
            break

    if "tipo" not in c and "serie" in c:  # la serie también dice el tipo: F factura, B boleta
        c["tipo"] = "boleta" if c["serie"][0] == "B" or c["serie"][:2] == "EB" else "factura"
        conf["tipo"] = 0.6

    for l in lineas:
        if (f := _fecha(l.plano)) is not None:
            c["fecha_emision"], conf["fecha_emision"] = f, l.confianza(f.strftime("%d%m%Y"))
            break

    if "DOLAR" in todo or "US$" in todo:
        c["moneda"], conf["moneda"] = "USD", 1.0
    elif "SOLES" in todo or "S/" in todo:
        c["moneda"], conf["moneda"] = "PEN", 1.0

    for l in lineas:
        m = RE_OC.search(l.texto.upper())
        if m:
            c["orden_compra"] = f"OC-{m[1]}-{_digitos(m[2])}"
            conf["orden_compra"] = l.confianza(m[0])
            break

    for l in lineas:
        p, montos = l.plano, RE_MONTO.findall(l.plano)
        if not montos:
            continue
        valor = a_numero(montos[-1])
        if "base_imponible" not in c and any(e in p for e in ETIQ_BASE):
            c["base_imponible"], conf["base_imponible"] = valor, l.confianza(montos[-1])
        elif "igv" not in c and RE_IGV.search(re.sub(r"[ .,]", "", p.split("S/")[0])) and "base_imponible" in c:
            c["igv"], conf["igv"] = valor, l.confianza(montos[-1])
        elif "total" not in c and any(e in p for e in ETIQ_TOTAL) and "SUB" not in p and "base_imponible" in c:
            c["total"], conf["total"] = valor, l.confianza(montos[-1])
    return Comprobante(**c), conf


def _digitos_en_contexto(t: str) -> str:
    """Corrige O/I/S solo dentro de secuencias que ya son mayormente dígitos."""
    return re.sub(r"[0-9OoIlS|]{9,}", lambda m: _digitos(m[0]), t)


# ------------------------------------------------------------- extractor

class ExtractorOCR:
    nombre = "tesseract + reglas"

    def __init__(self, idioma: str = "spa", psm: int = 6):
        import pytesseract  # import diferido para que los tests sin tesseract corran

        self.tess = pytesseract
        self.config = f"--psm {psm}"
        self.idioma = idioma

    def extraer(self, imagen: Path | Image.Image) -> Lectura:
        im = Image.open(imagen) if isinstance(imagen, (str, Path)) else imagen
        datos = self.tess.image_to_data(preparar(im), lang=self.idioma, config=self.config,
                                        output_type=self.tess.Output.DICT)
        lineas = _lineas(datos)
        comp, conf = parsear(lineas)
        return Lectura(comp, conf, "\n".join(l.texto for l in lineas), self.nombre)
