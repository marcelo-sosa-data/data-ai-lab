"""
Lectura del corpus: de markdown extraído de PDF a fragmentos por artículo.

Cada artículo es un fragmento con su vigencia. Cuando una resolución modifica
un artículo, el texto nuevo entra como otro fragmento con `vigente_desde` de
la resolución y el original queda con `vigente_hasta` el día anterior. Así el
buscador puede filtrar por la fecha de la consulta en vez de confiar en que el
texto nuevo "gane" por puntaje.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

RE_PIE = re.compile(r"^.*Secretaría General \| Pág\. \d+\s*$", re.MULTILINE)
RE_GUION = re.compile(r"(\w)-\n(\w)")
RE_ARTICULO = re.compile(r"^Artículo (\d+(?:-[A-Z])?)\.°(?: — (.+))?$", re.MULTILINE)
RE_CAPITULO = re.compile(r"^## (.+)$", re.MULTILINE)
RE_CAMBIO = re.compile(
    r"(?P<accion>Modificar|Incorporar) el artículo (?P<num>\d+(?:-[A-Z])?)\.° .*?\((?P<doc>[A-Z]+-\d{4})\)"
    r".*?«Artículo (?P=num)\.° — (?P<titulo>[^.]+)\. (?P<texto>.+?)»",
    re.DOTALL,
)


@dataclass(frozen=True)
class Fragmento:
    id: str
    documento: str            # código del reglamento al que pertenece el artículo
    titulo_documento: str
    capitulo: str
    articulo: str
    titulo: str
    texto: str
    vigente_desde: date
    vigente_hasta: date | None = None
    fuente: str = ""          # documento de donde sale el texto (el reglamento o la resolución)

    @property
    def cita(self) -> str:
        """Referencia corta para mostrar: 'RE-2024, art. 10 (mod. RCU-014-2026)'."""
        mod = f" (mod. {self.fuente})" if self.fuente and self.fuente != self.documento else ""
        return f"{self.documento}, art. {self.articulo}{mod}"

    @property
    def texto_indexable(self) -> str:
        return f"{self.titulo_documento}. {self.capitulo}. Artículo {self.articulo}. {self.titulo}. {self.texto}"

    def vigente(self, fecha: date) -> bool:
        return self.vigente_desde <= fecha and (self.vigente_hasta is None or fecha <= self.vigente_hasta)


def limpiar(texto: str) -> str:
    """Quita pies de página y une palabras cortadas con guion al final de línea."""
    texto = RE_PIE.sub("", texto)
    texto = RE_GUION.sub(r"\1\2", texto)
    return texto


def _frontmatter(crudo: str) -> tuple[dict, str]:
    if not crudo.startswith("---"):
        return {}, crudo
    _, cabecera, cuerpo = crudo.split("---", 2)
    meta = {}
    for linea in cabecera.strip().splitlines():
        clave, _, valor = linea.partition(":")
        meta[clave.strip()] = valor.strip()
    return meta, cuerpo


def leer_documento(ruta: Path) -> tuple[dict, list[dict]]:
    """Devuelve los metadatos y los artículos (num, titulo, capitulo, texto) de un archivo."""
    meta, cuerpo = _frontmatter(limpiar(ruta.read_text(encoding="utf-8")))
    capitulos = [(m.start(), m.group(1).strip()) for m in RE_CAPITULO.finditer(cuerpo)]
    encabezados = list(RE_ARTICULO.finditer(cuerpo))
    articulos = []
    for i, m in enumerate(encabezados):
        fin = encabezados[i + 1].start() if i + 1 < len(encabezados) else len(cuerpo)
        bloque = RE_CAPITULO.split(cuerpo[m.end():fin])[0]   # corta si empieza otro capítulo
        capitulo = next((c for pos, c in reversed(capitulos) if pos < m.start()), "")
        articulos.append({"num": m.group(1), "titulo": (m.group(2) or "").strip(),
                          "capitulo": capitulo, "texto": " ".join(bloque.split())})
    return meta, articulos


def cargar_corpus(carpeta: Path) -> list[Fragmento]:
    """Lee todos los documentos y aplica las resoluciones modificatorias."""
    fragmentos: dict[str, Fragmento] = {}
    resoluciones = []
    titulos = {}
    for ruta in sorted(Path(carpeta).glob("*.md")):
        meta, articulos = leer_documento(ruta)
        if meta.get("tipo") == "resolucion":
            resoluciones.append((meta, articulos))
            continue
        codigo = meta["codigo"]
        titulos[codigo] = meta["titulo"]
        desde = date.fromisoformat(meta["vigente_desde"])
        for a in articulos:
            f = Fragmento(f"{codigo}/art-{a['num']}", codigo, meta["titulo"], a["capitulo"], a["num"],
                          a["titulo"], a["texto"], desde, fuente=codigo)
            fragmentos[f.id] = f

    for meta, articulos in sorted(resoluciones, key=lambda r: r[0]["vigente_desde"]):
        desde = date.fromisoformat(meta["vigente_desde"])
        for a in articulos:
            m = RE_CAMBIO.search(a["texto"])
            if not m:
                continue          # artículos de forma: vigencia, publicación
            doc, num = m.group("doc"), m.group("num")
            base_id = f"{doc}/art-{num}"
            # el artículo que estaba vigente hasta hoy (original o una modificación previa)
            anterior = next((f for f in fragmentos.values()
                             if f.documento == doc and f.articulo == num and f.vigente_hasta is None), None)
            capitulo = anterior.capitulo if anterior else _capitulo_vecino(fragmentos, doc, num)
            if anterior:
                fragmentos[anterior.id] = replace(anterior, vigente_hasta=desde - timedelta(days=1))
            nuevo = Fragmento(f"{base_id}@{desde.isoformat()}", doc, titulos.get(doc, doc), capitulo, num,
                              m.group("titulo").strip(), " ".join(m.group("texto").split()), desde,
                              fuente=meta["codigo"])
            fragmentos[nuevo.id] = nuevo
    return list(fragmentos.values())


def _capitulo_vecino(fragmentos: dict[str, Fragmento], doc: str, num: str) -> str:
    """Para un artículo incorporado (35-A) usa el capítulo del artículo base (35)."""
    base = num.split("-")[0]
    f = fragmentos.get(f"{doc}/art-{base}")
    return f.capitulo if f else ""
