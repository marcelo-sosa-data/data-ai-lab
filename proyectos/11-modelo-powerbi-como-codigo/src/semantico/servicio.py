"""
Las mismas pruebas de medidas, contra el modelo ya publicado en el servicio.

El motor local prueba la lógica antes del merge. Después de publicar en test,
estas consultas corren en el modelo real (motor VertiPaq) por la API
executeQueries de Power BI, y así se confirma que el motor local y el servicio
dan lo mismo con los datos de ese ambiente.
"""

from __future__ import annotations

import time

import httpx

from .dax import parsear
from .pruebas import Caso

URL_API = "https://api.powerbi.com/v1.0/myorg"


def _literal(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return '"' + str(v).replace('"', '""') + '"'


def _ref(texto: str) -> str:
    col = parsear(texto)
    return f"'{col.tabla}'[{col.columna}]"


def consulta_dax(caso: Caso) -> str:
    """EVALUATE SUMMARIZECOLUMNS que reproduce el visual del caso."""
    partes = []
    if caso.por:
        partes.append(_ref(caso.por))
    for ref, valores in (caso.filtros or {}).items():
        valores = valores if isinstance(valores, (list, tuple)) else [valores]
        partes.append(f"TREATAS ( {{ {', '.join(_literal(v) for v in valores)} }}, {_ref(ref)} )")
    nombre = caso.medida.replace("]", "]]")
    partes.append(f'"valor", [{nombre}]')
    cuerpo = ",\n    ".join(partes)
    return f"EVALUATE\nSUMMARIZECOLUMNS (\n    {cuerpo}\n)"


class ClienteServicio:
    """Cliente mínimo de executeQueries; el token es de un service principal."""

    def __init__(self, dataset_id: str, token: str, http: httpx.Client | None = None):
        self.dataset_id = dataset_id
        self.http = http or httpx.Client(timeout=60)
        self.http.headers["Authorization"] = f"Bearer {token}"

    def ejecutar(self, dax: str) -> list[dict]:
        r = self.http.post(f"{URL_API}/datasets/{self.dataset_id}/executeQueries",
                           json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}})
        if r.status_code != 200:
            raise RuntimeError(f"executeQueries respondió {r.status_code}: {r.text[:300]}")
        cuerpo = r.json()
        resultado = cuerpo["results"][0]
        if "error" in resultado:
            raise RuntimeError(resultado["error"])
        return resultado["tables"][0]["rows"]

    def evaluar(self, caso: Caso) -> dict:
        filas = self.ejecutar(consulta_dax(caso))
        salida = {}
        clave_por = None
        if caso.por:
            col = parsear(caso.por)
            clave_por = f"{col.tabla}[{col.columna}]"
        for f in filas:
            valor = f.get("[valor]")
            if valor is None:
                continue
            salida[f.get(clave_por) if clave_por else None] = valor
        return salida

    def refrescar(self, workspace_id: str, intervalo: float = 15, maximo: float = 1800,
                  dormir=time.sleep) -> str:
        """Pide un refresco del modelo y espera a que termine. Devuelve el estado final."""
        base = f"{URL_API}/groups/{workspace_id}/datasets/{self.dataset_id}/refreshes"
        r = self.http.post(base, json={"notifyOption": "NoNotification"})
        if r.status_code not in (200, 202):
            raise RuntimeError(f"No se pudo pedir el refresco: {r.status_code} {r.text[:300]}")
        esperado = 0.0
        while esperado <= maximo:
            estado = self.http.get(base, params={"$top": 1}).json()["value"][0]["status"]
            if estado in ("Completed", "Failed", "Cancelled", "Disabled"):
                if estado != "Completed":
                    raise RuntimeError(f"El refresco terminó en {estado}")
                return estado
            dormir(intervalo)
            esperado += intervalo
        raise RuntimeError(f"El refresco no terminó en {maximo:.0f} s")
