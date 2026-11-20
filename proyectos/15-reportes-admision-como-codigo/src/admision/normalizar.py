"""Limpieza de textos, documentos, celulares y fechas que llegan de los exports."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def clave(texto) -> str:
    """Forma comparable de un texto: sin tildes, mayúsculas y espacios simples."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    return re.sub(r"\s+", " ", sin_tildes(str(texto)).upper()).strip()


def encabezado(texto: str) -> str:
    """'Fecha de registro' -> 'fecha_de_registro', 'Nro Documento' -> 'nro_documento'."""
    t = re.sub(r"[^a-z0-9]+", "_", sin_tildes(str(texto)).lower())
    return t.strip("_")


def mapear_catalogo(serie: pd.Series, catalogo: list[str]) -> pd.Series:
    """Lleva cada valor a su nombre oficial; lo que no está en el catálogo queda tal cual."""
    oficial = {clave(x): x for x in catalogo}
    return serie.map(lambda v: oficial.get(clave(v), clave(v) or None))


def documento(valor, tipo: str | None = None) -> str | None:
    """Documento como texto: sin espacios ni puntos, con los ceros que Excel se come."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    t = re.sub(r"[\s.\-]", "", str(valor)).upper()
    if not t:
        return None
    if t.isdigit():
        largo = 9 if (tipo == "CE" or len(t) == 9) else 8
        return t.zfill(largo)
    return t


def documento_sin_ceros(doc: str | None) -> str | None:
    """Para cruzar con tesorería, que guarda el documento como número."""
    if doc is None:
        return None
    return doc.lstrip("0") or "0"


def celular(valor) -> str | None:
    """Últimos 9 dígitos si es un móvil peruano (empieza con 9)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    digitos = re.sub(r"\D", "", str(valor))
    if len(digitos) >= 9 and digitos[-9] == "9":
        return digitos[-9:]
    return None


def referencia_codigo(valor) -> str | None:
    """Saca el código de postulante (10 dígitos) de la glosa de tesorería."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    m = re.search(r"(?<!\d)(\d{10})(?!\d)", str(valor))
    return m.group(1) if m else None


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")
_BARRA = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")


def fechas(serie: pd.Series) -> tuple[pd.Series, str | None]:
    """
    Convierte una columna de fechas que puede venir en ISO, dd/mm/aaaa o como
    fecha de Excel. Devuelve la serie y, si la hay, una descripción del problema.
    """
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie, None
    texto = serie.astype("string").str.strip().replace("", pd.NA)
    vacios = texto.isna()
    barras = texto.str.match(_BARRA, na=False)
    iso = texto.str.match(_ISO, na=False)
    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[us]")
    problema = None
    if barras.any():
        partes = texto[barras].str.extract(_BARRA).astype(int)
        primero_mayor = (partes[0] > 12).any()
        segundo_mayor = (partes[1] > 12).any()
        if segundo_mayor and not primero_mayor:
            problema = "fechas en formato mes/día"
            resultado[barras] = pd.to_datetime(texto[barras], format="%m/%d/%Y", exact=False, errors="coerce")
        else:
            resultado[barras] = pd.to_datetime(texto[barras], format="%d/%m/%Y %H:%M", errors="coerce")
            faltan = barras & resultado.isna()
            resultado[faltan] = pd.to_datetime(texto[faltan], format="%d/%m/%Y", errors="coerce")
    if iso.any():
        resultado[iso] = pd.to_datetime(texto[iso], format="ISO8601", errors="coerce")
    malas = ~vacios & resultado.isna()
    if malas.any() and problema is None:
        problema = f"{int(malas.sum())} fechas que no se pueden leer"
    return resultado, problema
