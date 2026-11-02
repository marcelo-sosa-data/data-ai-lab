"""
Normalización y términos para la búsqueda léxica.

El reglamento y los alumnos no usan las mismas palabras: el reglamento dice
"asignatura", "desaprobar" y "reserva de matrícula"; los alumnos, "curso",
"jalar" y "congelar". `expandir()` agrega a la consulta el término del
reglamento sin borrar el original. Solo se aplica a la pregunta, nunca a los
documentos.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import snowballstemmer

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual cuales
cualquier de del desde donde dos e el ella ellas ello ellos en entre era eres es esa esas ese eso esos esta
estas este esto estos estoy fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muy nada ni
no nos o otra otro para pero poco por porque que quien se sea segun ser si sin sobre solo son su sus tambien
te tengo tiene tu tus un una uno unos y ya yo puedo puede pueden debo hacer hago quiero cuanto cuanta cuantos
cuantas cuando hacia tan tanto
""".split())

# jerga o forma coloquial -> término del reglamento (patrones sobre texto normalizado)
SINONIMOS: dict[str, str] = {
    r"\bjal\w*": "desaprobar",
    r"\btri[ck]a\b": "tercera matricula",
    r"\bcongel\w*": "reserva matricula",
    r"\bcachimbo\w*": "ingresante",
    r"\bcurso\w*": "asignatura",
    r"\bciclo\w*": "semestre",
    r"\bmalla\b": "plan estudios",
    r"\bprofe\w*": "docente",
    r"\breclam\w*": "rectificacion",
    r"\bfalt(a|as|e|o)\b": "inasistencia",
    r"\bbot(an|en|aron|ar)\b": "separado",
    r"\bchapa\w*": "plagio",
    r"\bcopi(ando|ar|e|o)\b": "plagio",
    r"\bchatgpt\b|\b(ia)\b": "inteligencia artificial generativa",
    r"\bu\b": "universidad",
    r"\bplata\b": "pago devolucion",
    r"\bpago tarde\b|\bpagar tarde\b": "mora",
    r"\bturnitin\b": "similitud",
    r"\bchamb\w*": "trabajo",
    r"\bcambiar(me)? de carrera\b": "traslado interno",
    r"\botra (u|universidad)\b": "traslado convalidacion",
    r"\bpasa(r|rme)? aca\b": "traslado externo",
    r"\bse pasa\b|\bpaso un\b": "aprobatoria",
    r"\bterminar\b": "egresar",
    r"\bbec(a|ado|an)\b": "beca",
    r"\bdefender(me)?\b": "descargos",
    r"\bpsicolog\w*": "psicopedagogico",
    r"\bingles\b": "idioma extranjero",
}

_stem = snowballstemmer.stemmer("spanish")
_SIGNOS = re.compile(r"[^\w\s]")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni signos. La ñ se conserva."""
    texto = texto.lower().replace("ñ", "\0")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c)).replace("\0", "ñ")
    return " ".join(_SIGNOS.sub(" ", texto).split())


def expandir(texto_normalizado: str) -> str:
    """Agrega los términos del reglamento que corresponden a la jerga encontrada."""
    extra = [formal for patron, formal in SINONIMOS.items() if re.search(patron, texto_normalizado)]
    return " ".join([texto_normalizado, *extra])


@lru_cache(maxsize=20_000)
def raiz(palabra: str) -> str:
    return _stem.stemWord(palabra)


def terminos(texto: str, con_sinonimos: bool = False) -> list[str]:
    """Texto -> lista de raíces sin stopwords, lista para BM25."""
    norm = normalizar(texto)
    if con_sinonimos:
        norm = expandir(norm)
    return [raiz(t) for t in norm.split() if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]
