"""
Construcción por ambiente, plan de cambios y publicación en Fabric.

construir(): copia el modelo y reemplaza los parámetros del ambiente.
plan():      compara dos versiones del modelo (la del PR contra main) y
             calcula cuánto cambian los números de las medidas tocadas, para
             que quien revisa el PR vea el efecto y no solo el diff del DAX.
publicar():  sube la carpeta construida a un workspace con fabric-cicd.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .dax import ErrorDAX
from .motor import Motor
from .tmdl import Modelo, cargar_modelo, modelo_desde_textos

NOMBRE_MODELO = "Matricula.SemanticModel"


def cargar_ambientes(ruta: str | Path) -> dict:
    ambientes = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    for nombre, a in ambientes.items():
        if "parametros" not in a:
            raise ValueError(f"El ambiente {nombre} no tiene parametros")
    return ambientes


# ------------------------------------------------------------------ construir

def construir(carpeta_modelo: str | Path, ambiente: str, ambientes: dict, salida: str | Path) -> Path:
    """Escribe salida/<ambiente>/<modelo> con los parámetros del ambiente y lo verifica."""
    if ambiente not in ambientes:
        raise ValueError(f"Ambiente desconocido: {ambiente}. Hay: {sorted(ambientes)}")
    carpeta_modelo = Path(carpeta_modelo)
    destino = Path(salida) / ambiente / carpeta_modelo.name
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(carpeta_modelo, destino)
    archivo = destino / "definition" / "expressions.tmdl"
    texto = archivo.read_text(encoding="utf-8")
    for nombre, valor in ambientes[ambiente]["parametros"].items():
        patron = re.compile(rf'^(expression {re.escape(nombre)} = )"[^"]*"', re.MULTILINE)
        if not patron.search(texto):
            raise ValueError(f"El parámetro {nombre} no está en expressions.tmdl")
        texto = patron.sub(lambda m: f'{m.group(1)}"{valor}"', texto)
    archivo.write_text(texto, encoding="utf-8")

    modelo = cargar_modelo(destino)
    for nombre, valor in ambientes[ambiente]["parametros"].items():
        if modelo.parametros.get(nombre) != valor:
            raise ValueError(f"{nombre} quedó en {modelo.parametros.get(nombre)!r} y debía ser {valor!r}")
    # ningún valor de otro ambiente debe quedar en el TMDL construido
    todo = "\n".join(p.read_text(encoding="utf-8") for p in destino.rglob("*.tmdl"))
    for otro, a in ambientes.items():
        if otro == ambiente:
            continue
        for valor in a["parametros"].values():
            if valor in todo and valor not in ambientes[ambiente]["parametros"].values():
                raise ValueError(f"El modelo de {ambiente} todavía tiene el valor de {otro}: {valor}")
    return destino


# ------------------------------------------------------------------ plan

@dataclass
class Cambio:
    tipo: str      # medida | relacion | columna | parametro
    accion: str    # nueva | eliminada | modificada
    objeto: str
    detalle: str = ""


@dataclass
class Impacto:
    medida: str
    antes: float | None
    despues: float | None
    porcentaje: bool = False

    @property
    def variacion(self) -> float | None:
        if self.antes in (None, 0) or self.despues is None:
            return None
        return self.despues / self.antes - 1


@dataclass
class Plan:
    cambios: list[Cambio] = field(default_factory=list)
    impactos: list[Impacto] = field(default_factory=list)
    filtros: dict = field(default_factory=dict)


def _clave_rel(r) -> str:
    return f"{r.tabla_desde}.{r.columna_desde} -> {r.tabla_hacia}.{r.columna_hacia}"


def comparar_modelos(base: Modelo, nuevo: Modelo) -> list[Cambio]:
    cambios = []
    mb, mn = base.medidas, nuevo.medidas
    for n in sorted(set(mn) - set(mb)):
        cambios.append(Cambio("medida", "nueva", n))
    for n in sorted(set(mb) - set(mn)):
        cambios.append(Cambio("medida", "eliminada", n))
    for n in sorted(set(mb) & set(mn)):
        a, b = mb[n], mn[n]
        partes = []
        if " ".join(a.expresion.split()) != " ".join(b.expresion.split()):
            partes.append("expresión")
        if a.formato != b.formato:
            partes.append(f"formato {a.formato!r} -> {b.formato!r}")
        if a.descripcion != b.descripcion:
            partes.append("descripción")
        if a.carpeta != b.carpeta:
            partes.append(f"carpeta {a.carpeta!r} -> {b.carpeta!r}")
        if partes:
            cambios.append(Cambio("medida", "modificada", n, ", ".join(partes)))
    rb = {_clave_rel(r): r for r in base.relaciones}
    rn = {_clave_rel(r): r for r in nuevo.relaciones}
    for k in sorted(set(rn) - set(rb)):
        cambios.append(Cambio("relacion", "nueva", k))
    for k in sorted(set(rb) - set(rn)):
        cambios.append(Cambio("relacion", "eliminada", k))
    for k in sorted(set(rb) & set(rn)):
        a, b = rb[k], rn[k]
        if (a.bidireccional, a.activa) != (b.bidireccional, b.activa):
            cambios.append(Cambio("relacion", "modificada", k,
                                  f"bidireccional {a.bidireccional} -> {b.bidireccional}, "
                                  f"activa {a.activa} -> {b.activa}"))
    cb = {(t, c) for t, tb in base.tablas.items() for c in tb.columnas}
    cn = {(t, c) for t, tn in nuevo.tablas.items() for c in tn.columnas}
    for t, c in sorted(cn - cb):
        cambios.append(Cambio("columna", "nueva", f"{t}[{c}]"))
    for t, c in sorted(cb - cn):
        cambios.append(Cambio("columna", "eliminada", f"{t}[{c}]"))
    for p in sorted(set(base.parametros) | set(nuevo.parametros)):
        if base.parametros.get(p) != nuevo.parametros.get(p):
            cambios.append(Cambio("parametro", "modificada", p))
    return cambios


def _medidas_que_dependen(modelo: Modelo, nombres: set[str]) -> set[str]:
    """Las medidas tocadas y todas las que las usan, directa o indirectamente."""
    from .dax import parsear, referencias
    usa = {}
    for n, m in modelo.medidas.items():
        try:
            usa[n] = referencias(parsear(m.expresion))[1]
        except ErrorDAX:
            usa[n] = set()
    afectadas = set(nombres)
    while True:
        nuevas = {n for n, refs in usa.items() if refs & afectadas} - afectadas
        if not nuevas:
            return afectadas
        afectadas |= nuevas


def plan(base: Modelo, nuevo: Modelo, carpeta_datos: str | Path | None = None,
         filtros: dict | None = None) -> Plan:
    """Cambios entre versiones y, si hay datos, el valor antes y después de cada medida afectada."""
    p = Plan(comparar_modelos(base, nuevo), filtros=filtros or {})
    if carpeta_datos is None:
        return p
    tocadas = {c.objeto for c in p.cambios if c.tipo == "medida" and c.accion != "eliminada"
               and ("expresión" in c.detalle or c.accion == "nueva")}
    if any(c.tipo in ("relacion", "columna") for c in p.cambios):
        tocadas |= set(nuevo.medidas)
    if not tocadas:
        return p
    afectadas = _medidas_que_dependen(nuevo, tocadas)
    motor_b, motor_n = _motor_o_none(base, carpeta_datos), _motor_o_none(nuevo, carpeta_datos)
    for n in sorted(afectadas):
        antes = _valor(motor_b, n, p.filtros) if n in base.medidas else None
        despues = _valor(motor_n, n, p.filtros)
        if antes != despues:
            p.impactos.append(Impacto(n, antes, despues, "%" in nuevo.medidas[n].formato))
    return p


def _motor_o_none(modelo: Modelo, carpeta) -> Motor | None:
    try:
        return Motor.desde_carpeta(modelo, carpeta)
    except ErrorDAX:
        return None


def _valor(motor: Motor | None, medida: str, filtros: dict):
    if motor is None:
        return None
    try:
        return motor.evaluar(medida, filtros).get(None)
    except ErrorDAX:
        return None


def modelo_en_git(ref: str, carpeta: str | Path, repo: str | Path = ".") -> Modelo:
    """Lee el modelo tal como está en un commit o rama (p. ej. origin/main)."""
    carpeta = Path(carpeta).resolve()
    raiz = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo, check=True,
                               capture_output=True, text=True).stdout.strip())
    definicion = (carpeta / "definition") if (carpeta / "definition").is_dir() else carpeta
    rel = definicion.relative_to(raiz).as_posix()
    archivos = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, "--", rel], cwd=raiz,
                              check=True, capture_output=True, text=True).stdout.split()
    textos = {}
    for a in archivos:
        if a.endswith(".tmdl"):
            textos[a[len(rel) + 1:]] = subprocess.run(["git", "show", f"{ref}:{a}"], cwd=raiz, check=True,
                                                       capture_output=True, text=True).stdout
    if not textos:
        raise ValueError(f"No hay archivos TMDL en {ref}:{rel}")
    return modelo_desde_textos(textos)


def _fmt(v) -> str:
    if v is None:
        return "(en blanco)"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.4f}" if abs(v) < 1 else f"{v:,.2f}"
    return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)


def plan_markdown(p: Plan, titulo: str = "Cambios en el modelo") -> str:
    lineas = [f"### {titulo}", ""]
    if not p.cambios:
        lineas.append("Sin cambios en medidas, relaciones, columnas ni parámetros.")
        return "\n".join(lineas) + "\n"
    lineas += ["| Tipo | Cambio | Objeto | Detalle |", "|---|---|---|---|"]
    for c in p.cambios:
        lineas.append(f"| {c.tipo} | {c.accion} | {c.objeto} | {c.detalle} |")
    if p.impactos:
        filtro = ", ".join(f"{k} = {v}" for k, v in p.filtros.items()) or "sin filtros"
        lineas += ["", f"Valores que cambian ({filtro}):", "",
                   "| Medida | Antes | Después | Variación |", "|---|---:|---:|---:|"]
        for i in p.impactos:
            if i.porcentaje:
                f = lambda v: "(en blanco)" if v is None else f"{v:.1%}"  # noqa: E731
                var = f"{(i.despues - i.antes) * 100:+.1f} pp" if None not in (i.antes, i.despues) else ""
            else:
                f = _fmt
                var = f"{i.variacion:+.1%}" if i.variacion is not None else ""
            lineas.append(f"| {i.medida} | {f(i.antes)} | {f(i.despues)} | {var} |")
    return "\n".join(lineas) + "\n"


# ------------------------------------------------------------------ publicar

def publicar(carpeta_construida: str | Path, ambiente: str, ambientes: dict) -> dict:
    """Publica el modelo construido en el workspace del ambiente con fabric-cicd.

    Necesita AZURE_TENANT_ID, AZURE_CLIENT_ID y AZURE_CLIENT_SECRET de un
    service principal con rol de colaborador en el workspace, y la variable con
    el id del workspace que indica ambientes.yaml.
    """
    from azure.identity import ClientSecretCredential
    from fabric_cicd import FabricWorkspace, publish_all_items

    a = ambientes[ambiente]
    faltan = [v for v in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
                          a["variable_workspace_id"]) if not os.getenv(v)]
    if faltan:
        raise RuntimeError(f"Faltan variables de entorno para publicar en {ambiente}: {faltan}")
    credencial = ClientSecretCredential(os.environ["AZURE_TENANT_ID"], os.environ["AZURE_CLIENT_ID"],
                                        os.environ["AZURE_CLIENT_SECRET"])
    carpeta = Path(carpeta_construida)
    repositorio = carpeta.parent if carpeta.name.endswith(".SemanticModel") else carpeta
    ws = FabricWorkspace(workspace_id=os.environ[a["variable_workspace_id"]],
                         repository_directory=str(repositorio), item_type_in_scope=["SemanticModel"],
                         environment=ambiente.upper(), token_credential=credencial)
    publish_all_items(ws)
    return {"ambiente": ambiente, "workspace": a["workspace"], "carpeta": str(repositorio)}
