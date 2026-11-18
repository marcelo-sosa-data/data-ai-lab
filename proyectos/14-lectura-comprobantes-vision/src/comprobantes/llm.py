"""
Extractor con un modelo de visión por la API de chat completions.

Funciona con cualquier endpoint compatible (OpenAI, Groq, Together, vLLM u
Ollama con un modelo multimodal) cambiando LLM_BASE_URL y LLM_MODELO. La
imagen va en base64 en el mensaje y la respuesta se pide con JSON schema
estricto, así que llega siempre con los mismos campos y tipos.

El modelo no da una confianza por campo comparable con la de Tesseract, así
que con este extractor el ruteo se apoya solo en las validaciones.
"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

from PIL import Image

from .esquema import Comprobante, esquema_json
from .ocr import Lectura

MODELO_DEFECTO = "gpt-4.1-mini"

SISTEMA = """Lees comprobantes de pago peruanos (facturas y boletas electrónicas) para cuentas por pagar.
Devuelve solo lo que está impreso en la imagen, con estas reglas:
- tipo: "factura" o "boleta" según el título del documento.
- ruc_emisor es el RUC de quien emite (cabecera); ruc_receptor, el del cliente (Señor(es), Cliente).
- serie: los 4 caracteres antes del guion (F001, E001, B001, FA01). numero: el correlativo sin ceros a la izquierda.
- fecha_emision en formato AAAA-MM-DD.
- moneda: PEN si dice soles o S/, USD si dice dólares o US$.
- base_imponible es la operación gravada, sub total o valor de venta, sin IGV.
- Copia los montos tal como están, aunque no cuadren entre sí. No calcules un campo que no se lee: déjalo en null.
- orden_compra solo si aparece un código OC-AAAA-NNNNN (puede estar en Observación u O/C).
"""


def imagen_a_data_url(imagen: Path | Image.Image, lado_max: int = 1600) -> str:
    im = Image.open(imagen) if isinstance(imagen, (str, Path)) else imagen
    im = im.convert("RGB")
    if max(im.size) > lado_max:  # más píxeles no ayudan y suben el costo en tokens
        f = lado_max / max(im.size)
        im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class ExtractorLLM:
    def __init__(self, modelo: str | None = None, max_tokens: int = 1500):
        from openai import OpenAI  # import diferido: el modo demo no necesita el SDK

        clave = os.getenv("LLM_API_KEY")
        if not clave:
            raise RuntimeError("Falta LLM_API_KEY. Cópiala en un archivo .env o usa --demo.")
        self.cliente = OpenAI(api_key=clave, base_url=os.getenv("LLM_BASE_URL") or None)
        self.nombre = modelo or os.getenv("LLM_MODELO", MODELO_DEFECTO)
        self.max_tokens = max_tokens
        self.tokens_entrada = self.tokens_salida = 0

    def extraer(self, imagen: Path | Image.Image) -> Lectura:
        r = self.cliente.chat.completions.create(
            model=self.nombre,
            temperature=0,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": SISTEMA},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extrae los campos de este comprobante."},
                    {"type": "image_url", "image_url": {"url": imagen_a_data_url(imagen), "detail": "high"}},
                ]},
            ],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "comprobante", "strict": True, "schema": esquema_json()}},
        )
        if r.usage:
            self.tokens_entrada += r.usage.prompt_tokens
            self.tokens_salida += r.usage.completion_tokens
        contenido = r.choices[0].message.content or "{}"
        try:
            comp = Comprobante.model_validate(json.loads(contenido))
        except (json.JSONDecodeError, ValueError):
            comp = Comprobante()  # respuesta inválida: todo a revisión por campos faltantes
        return Lectura(comp, {}, contenido, self.nombre)


class ExtractorGuionado:
    """Devuelve lecturas predefinidas por nombre de archivo. Para tests."""

    nombre = "guionado"

    def __init__(self, lecturas: dict[str, Comprobante], confianza: float | None = 0.95):
        self.lecturas = lecturas
        self.confianza = confianza

    def extraer(self, imagen: Path) -> Lectura:
        comp = self.lecturas[Path(imagen).name]
        conf = {k: self.confianza for k in Comprobante.model_fields} if self.confianza is not None else {}
        return Lectura(comp, conf, "", self.nombre)
