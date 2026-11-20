"""
Genera los exports de admisión de la Universidad Mirasol (ficticia) para tres
campañas: 2026-1 y 2026-2 cerradas, y 2027-1 en curso con corte al 15/11/2026.

Por campaña salen los tres archivos que hoy se descargan cada lunes:
  - admision_inscripciones_<campaña>.csv   sistema de admisión, una fila por inscripción
  - crm_interesados_<campaña>.xlsx         leads del CRM de Marketing
  - tesoreria_pagos_<campaña>.xlsx         pagos de derecho de admisión y matrícula
más vacantes_<campaña>.csv, que mantiene la Oficina de Admisión.

Lo que traen, como los exports reales:
  - el sistema de admisión cambió en abril de 2026: 2026-1 sale en CSV con ';',
    cp1252, encabezados viejos y fechas dd/mm/aaaa; desde 2026-2 sale en UTF-8,
    con ',', otros encabezados, fechas ISO y textos en mayúsculas sin tildes
  - una persona puede tener varias inscripciones (vuelve a dar el examen, o
    pasa de quinto superior al examen), y el export repite filas cuando una
    inscripción se edita
  - registros de prueba que deja el equipo de sistemas
  - tesorería guarda el documento del pagador como número (pierde los ceros
    de la izquierda) y a veces paga el apoderado; la referencia al código de
    postulante viene en la mayoría de pagos, con espacios o prefijos
  - el CRM no siempre tiene documento y el celular viene en cualquier formato
  - en 2027-1 aparece la modalidad Beca Mirasol, Lima Norte cae (abrió un
    competidor cerca) y quinto superior crece por los convenios con colegios

La verdad de cada campaña (quién es persona real, quién ingresó y quién se
matriculó al corte) queda en verdad/<campaña>.parquet, y la de 2027-1 al
cierre en verdad/2027-1_cierre.parquet. El pipeline no la lee;
solo sirve para medir cuánto se equivoca cada forma de reportar.

Uso:
    python datos/generar_datos.py                 # ~10 s
    python datos/generar_datos.py --escala 0.2    # chico, para pruebas
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SALIDA_DEFECTO = Path(__file__).parent
CORTE = date(2026, 11, 15)


@dataclass(frozen=True)
class Campania:
    codigo: str
    inicio: date
    cierre: date
    examenes: tuple[date, ...]
    personas: int
    perfil: str          # "primer" o "segundo" semestre


CAMPANIAS = [
    Campania("2026-1", date(2025, 8, 4), date(2026, 3, 20),
             (date(2025, 10, 18), date(2025, 12, 13), date(2026, 2, 7), date(2026, 3, 7)), 3150, "primer"),
    Campania("2026-2", date(2026, 3, 30), date(2026, 8, 14),
             (date(2026, 5, 16), date(2026, 6, 27), date(2026, 7, 25)), 1650, "segundo"),
    Campania("2027-1", date(2026, 8, 3), date(2027, 3, 19),
             (date(2026, 10, 17), date(2026, 12, 12), date(2027, 2, 6), date(2027, 3, 6)), 3150, "primer"),
]

SEDES = {"Lima Norte": 0.45, "Lima Centro": 0.35, "Arequipa": 0.20}
CARRERAS = {
    "Ingeniería Industrial": 0.17, "Ingeniería de Sistemas": 0.14, "Ingeniería Civil": 0.10,
    "Administración": 0.15, "Contabilidad": 0.10, "Marketing": 0.08,
    "Psicología": 0.14, "Derecho": 0.12,
}
# adultos que trabajan se van más a negocios
CARRERAS_ADULTOS = {
    "Ingeniería Industrial": 0.16, "Ingeniería de Sistemas": 0.10, "Ingeniería Civil": 0.05,
    "Administración": 0.28, "Contabilidad": 0.22, "Marketing": 0.08,
    "Psicología": 0.06, "Derecho": 0.05,
}
# modalidad: participación, prob. de ingresar, prob. de matricularse si ingresa, derecho S/
MODALIDADES = {
    "Examen de admisión": (0.46, 0.62, 0.82, 250),
    "Quinto superior": (0.24, 0.90, 0.86, 150),
    "Primeros puestos": (0.05, 0.97, 0.90, 0),
    "Traslado externo": (0.10, 0.84, 0.88, 300),
    "Adultos que trabajan": (0.15, 0.80, 0.78, 200),
    "Beca Mirasol": (0.05, 0.38, 0.95, 100),
}
MONTO_MATRICULA = 480.0

CANALES = ["Colegios en convenio", "Ferias escolares", "Referidos", "Web", "WhatsApp", "Redes sociales"]
# tasa de conversión lead -> postulante por canal
CONVERSION_CANAL = {"Colegios en convenio": 0.30, "Ferias escolares": 0.21, "Referidos": 0.33,
                    "Web": 0.16, "WhatsApp": 0.11, "Redes sociales": 0.055}
PESO_CANAL = {
    "general": [0.10, 0.14, 0.12, 0.30, 0.16, 0.18],
    "colegio": [0.34, 0.30, 0.08, 0.14, 0.06, 0.08],   # quinto superior y primeros puestos
}

NOMBRES = ["Luis", "José", "Carlos", "Jorge", "Miguel", "Diego", "Renzo", "Bruno", "Piero", "Sebastián",
           "Mateo", "Gabriel", "Fernando", "Ricardo", "Kevin", "Jhon", "Alonso", "Marco", "Andrés", "Josué",
           "María", "Lucía", "Valeria", "Camila", "Daniela", "Fiorella", "Andrea", "Rosa", "Milagros",
           "Ximena", "Alejandra", "Mariana", "Claudia", "Gianella", "Sofía", "Kiara", "Nicole", "Diana",
           "Brenda", "Allison"]
APELLIDOS = ["Quispe", "Flores", "Sánchez", "Rodríguez", "García", "Rojas", "Huamán", "Mendoza", "Torres",
             "Chávez", "Ramírez", "Vásquez", "Castillo", "Díaz", "Mamani", "Espinoza", "Gutiérrez",
             "Vargas", "Romero", "Salazar", "Ccori", "Paredes", "Cárdenas", "Benites", "Ríos", "Valdivia",
             "Llanos", "Zevallos", "Condori", "Herrera", "Medina", "Aguilar", "Cruz", "Gonzales", "Lozano",
             "Silva", "Ticona", "Apaza", "Morales", "Navarro"]


# --------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------

def _sin_tildes(texto: str) -> str:
    tabla = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")
    return texto.translate(tabla)


def _perfil_diario(c: Campania) -> np.ndarray:
    """Peso de cada día de la campaña para la fecha de inscripción."""
    dias = (c.cierre - c.inicio).days + 1
    f = np.arange(dias) / dias
    if c.perfil == "primer":
        # arranca lento en agosto, sube en noviembre, pico en enero y febrero
        peso = 0.35 + 2.4 * np.exp(-((f - 0.70) / 0.17) ** 2) + 0.5 * np.exp(-((f - 0.40) / 0.08) ** 2)
    else:
        peso = 0.45 + 2.0 * np.exp(-((f - 0.70) / 0.20) ** 2)
    fechas = [c.inicio + timedelta(days=int(i)) for i in range(dias)]
    # menos inscripciones el domingo, la última semana de diciembre y en Fiestas Patrias
    for i, d in enumerate(fechas):
        if d.weekday() == 6:
            peso[i] *= 0.45
        if (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day == 1) or (d.month == 7 and d.day in (28, 29)):
            peso[i] *= 0.4
    return peso / peso.sum()


class Documentos:
    """Reparte documentos únicos en todas las campañas."""

    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.usados: set[str] = set()

    def nuevo(self) -> tuple[str, str]:
        while True:
            u = self.rng.random()
            if u < 0.955:
                tipo = "DNI"
                # una parte de los DNI empieza con cero
                primero = 0 if self.rng.random() < 0.11 else int(self.rng.integers(1, 8))
                doc = f"{primero}{self.rng.integers(0, 10**7):07d}"
            elif u < 0.99:
                tipo = "CE"
                doc = f"00{self.rng.integers(1000000, 9999999):07d}"
            else:
                tipo = "PAS"
                letras = "ABCDEFGHJKLMNPRSTUVWXYZ"
                doc = "".join(self.rng.choice(list(letras), 2)) + f"{self.rng.integers(100000, 999999)}"
            if doc not in self.usados:
                self.usados.add(doc)
                return tipo, doc


def _celular(rng) -> str:
    return f"9{rng.integers(0, 10**8):08d}"


def _celular_crm(cel: str, rng) -> str:
    u = rng.random()
    if u < 0.55:
        return cel
    if u < 0.75:
        return f"+51 {cel[:3]} {cel[3:6]} {cel[6:]}"
    if u < 0.90:
        return f"{cel[:3]}-{cel[3:6]}-{cel[6:]}"
    return f"51{cel}"


# --------------------------------------------------------------------------
# simulación de una campaña
# --------------------------------------------------------------------------

def _simular_campania(c: Campania, escala: float, rng: np.random.Generator, docs: Documentos) -> dict:
    perfil = _perfil_diario(c)
    dias = len(perfil)
    nueva = c.codigo == "2027-1"

    sedes = list(SEDES)
    mods = [m for m in MODALIDADES if nueva or m != "Beca Mirasol"]
    personas: list[dict] = []
    for sede in sedes:
        for mod in mods:
            esperado = c.personas * escala * SEDES[sede] * MODALIDADES[mod][0]
            if nueva:
                esperado *= {"Lima Norte": 0.83, "Lima Centro": 0.99, "Arequipa": 1.01}[sede]
                if mod == "Quinto superior":
                    esperado *= 1.18
            for _ in range(rng.poisson(esperado)):
                personas.append({"sede": sede, "modalidad": mod})

    rng.shuffle(personas)
    inscripciones: list[dict] = []
    secuencia = 0

    def inscribir(p: dict, mod: str, fecha: date) -> dict | None:
        """Crea la inscripción y resuelve su evaluación."""
        nonlocal secuencia
        if mod == "Examen de admisión":
            examen = next((e for e in c.examenes if e >= fecha + timedelta(days=3)), None)
            if examen is None:
                return None
            fecha_eval = examen
        else:
            fecha_eval = fecha + timedelta(days=int(rng.integers(4, 16)))
            if fecha_eval > c.cierre - timedelta(days=3):
                return None
        secuencia += 1
        ins = {
            "codigo_postulante": f"{c.codigo.replace('-', '')}{secuencia:05d}",
            "id_persona": p["id_persona"], "modalidad": mod, "carrera": p["carrera"], "sede": p["sede"],
            "fecha_inscripcion": datetime.combine(fecha, datetime.min.time())
            + timedelta(hours=int(rng.integers(8, 21)), minutes=int(rng.integers(0, 60))),
            "estado": "Inscrito", "puntaje": None, "fecha_resultado": None,
        }
        if rng.random() < 0.03:
            ins["estado"] = "Anulado"
            ins["fecha_actualizacion"] = ins["fecha_inscripcion"] + timedelta(days=int(rng.integers(1, 6)))
            inscripciones.append(ins)
            return ins
        asiste = rng.random() < (0.90 if mod == "Examen de admisión" else 0.96)
        if asiste:
            p_ingreso = MODALIDADES[mod][1]
            if mod == "Examen de admisión":
                puntaje = float(np.clip(rng.normal(55, 13), 5, 100))
                ingresa = puntaje >= 49.5
                ins["puntaje"] = round(puntaje, 1)
            else:
                ingresa = rng.random() < p_ingreso
            ins["estado"] = "Ingresó" if ingresa else "No ingresó"
            ins["fecha_resultado"] = fecha_eval
        ins["fecha_actualizacion"] = (datetime.combine(ins["fecha_resultado"] or fecha, datetime.min.time())
                                      + timedelta(hours=18))
        inscripciones.append(ins)
        return ins

    reales = []
    for p in personas:
        tipo, doc = docs.nuevo()
        sexo_f = rng.random() < 0.52
        nombre = rng.choice(NOMBRES[20:] if sexo_f else NOMBRES[:20])
        if rng.random() < 0.4:
            nombre = f"{nombre} {rng.choice(NOMBRES[20:] if sexo_f else NOMBRES[:20])}"
        p.update({
            "id_persona": len(reales) + 1, "tipo_documento": tipo, "documento": doc,
            "nombres": nombre, "ap_paterno": rng.choice(APELLIDOS), "ap_materno": rng.choice(APELLIDOS),
            "celular": _celular(rng),
        })
        pesos = CARRERAS_ADULTOS if p["modalidad"] == "Adultos que trabajan" else CARRERAS
        p["carrera"] = rng.choice(list(pesos), p=np.array(list(pesos.values())) / sum(pesos.values()))
        fecha = c.inicio + timedelta(days=int(rng.choice(dias, p=perfil)))
        ins = inscribir(p, p["modalidad"], fecha)
        if ins is None:
            # se inscribió tarde para el último examen o el último expediente: adelanta la fecha
            fecha = c.inicio + timedelta(days=int(rng.choice(dias, p=perfil) * 0.85))
            ins = inscribir(p, p["modalidad"], fecha)
            if ins is None:
                continue
        reales.append(p)
        # segundas oportunidades
        actual = ins
        for _ in range(3):
            if actual["estado"] != "No ingresó":
                break
            if actual["modalidad"] == "Examen de admisión" and rng.random() < 0.35:
                nueva_mod = "Examen de admisión"
            elif actual["modalidad"] in ("Quinto superior", "Beca Mirasol") and rng.random() < 0.5:
                nueva_mod = "Examen de admisión"
            else:
                break
            fecha = actual["fecha_resultado"] + timedelta(days=int(rng.integers(2, 20)))
            if fecha > c.cierre - timedelta(days=5):
                break
            siguiente = inscribir(p, nueva_mod, fecha)
            if siguiente is None:
                break
            actual = siguiente

    ins_df = pd.DataFrame(inscripciones)
    per_df = pd.DataFrame(reales)

    # matrícula: primera inscripción con la que la persona ingresó
    ingresos = (ins_df[ins_df["estado"] == "Ingresó"].sort_values("fecha_resultado")
                .drop_duplicates("id_persona"))
    pagos_mat = []
    for _, r in ingresos.iterrows():
        p_mat = MODALIDADES[r["modalidad"]][2]
        if nueva and r["sede"] == "Lima Norte":
            p_mat -= 0.07
        if rng.random() >= p_mat:
            continue
        # se paga antes cuanto más cerca está el inicio de clases
        restante = (c.cierre - r["fecha_resultado"]).days
        demora = int(min(rng.exponential(9 if restante > 40 else 4), max(restante, 0)))
        fecha = r["fecha_resultado"] + timedelta(days=1 + demora)
        if fecha > c.cierre:
            fecha = c.cierre
        pagos_mat.append({"codigo_postulante": r["codigo_postulante"], "id_persona": r["id_persona"],
                          "fecha_pago": datetime.combine(fecha, datetime.min.time())
                          + timedelta(hours=int(rng.integers(8, 20)), minutes=int(rng.integers(0, 60)))})
    mat_df = pd.DataFrame(pagos_mat)
    return {"personas": per_df, "inscripciones": ins_df, "matriculas": mat_df}


def _aplicar_corte(sim: dict, corte: date) -> dict:
    """Deja solo lo que se sabía al corte (para la campaña en curso)."""
    ins = sim["inscripciones"].copy()
    ins = ins[ins["fecha_inscripcion"].dt.date <= corte].copy()
    pendiente = ins["fecha_resultado"].notna() & (pd.to_datetime(ins["fecha_resultado"]).dt.date > corte)
    ins.loc[pendiente, ["estado", "puntaje", "fecha_resultado"]] = ["Inscrito", None, None]
    tope = datetime.combine(corte, datetime.max.time())
    ins.loc[pendiente, "fecha_actualizacion"] = ins.loc[pendiente, "fecha_inscripcion"] + timedelta(hours=1)
    ins["fecha_actualizacion"] = ins["fecha_actualizacion"].where(ins["fecha_actualizacion"] <= tope, tope)
    mat = sim["matriculas"]
    mat = mat[(mat["fecha_pago"].dt.date <= corte) & mat["codigo_postulante"].isin(ins["codigo_postulante"])]
    per = sim["personas"][sim["personas"]["id_persona"].isin(ins["id_persona"])]
    return {"personas": per.copy(), "inscripciones": ins, "matriculas": mat.copy()}


# --------------------------------------------------------------------------
# exports con el formato de cada sistema
# --------------------------------------------------------------------------

def _nombre_viejo(p) -> str:
    return f"{p['ap_paterno']} {p['ap_materno']}, {p['nombres']}".upper()


def _nombre_nuevo(p) -> str:
    return _sin_tildes(f"{p['nombres']} {p['ap_paterno']} {p['ap_materno']}").upper()


def _export_admision(c: Campania, sim: dict, rng, carpeta: Path) -> None:
    ins = sim["inscripciones"].merge(sim["personas"], on="id_persona", suffixes=("", "_p"))
    ins = ins.drop(columns=[x for x in ins.columns if x.endswith("_p")])
    viejo = c.codigo == "2026-1"

    filas = []
    for _, r in ins.iterrows():
        doc = r["documento"]
        if rng.random() < 0.015:
            doc = f"{doc[:4]} {doc[4:]}" if rng.random() < 0.5 else f" {doc} "
        filas.append({**r.to_dict(), "documento_export": doc})
    df = pd.DataFrame(filas)

    # versiones anteriores de inscripciones editadas
    editadas = df[df["estado"].isin(["Ingresó", "No ingresó"])].sample(frac=0.025, random_state=int(rng.integers(1e9)))
    previas = editadas.copy()
    previas["estado"] = "Inscrito"
    previas["puntaje"] = None
    previas["fecha_resultado"] = None
    previas["fecha_actualizacion"] = previas["fecha_inscripcion"] + timedelta(hours=2)
    # y algunas filas repetidas tal cual
    repetidas = df.sample(frac=0.008, random_state=int(rng.integers(1e9)))
    df = pd.concat([df, previas, repetidas], ignore_index=True)

    # registros de prueba de sistemas
    pruebas = []
    for i in range(12):
        f = c.inicio + timedelta(days=int(rng.integers(0, 40)))
        pruebas.append({
            "codigo_postulante": f"{c.codigo.replace('-', '')}9{i:04d}", "tipo_documento": "DNI",
            "documento_export": "00000000" if i % 2 else "12345678",
            "nombres": "PRUEBA", "ap_paterno": "SISTEMAS", "ap_materno": f"ADMISION {i + 1}",
            "celular": "999999999", "modalidad": "Examen de admisión" if i % 3 else "Quinto superior",
            "carrera": list(CARRERAS)[i % 8], "sede": list(SEDES)[i % 3],
            "fecha_inscripcion": datetime.combine(f, datetime.min.time()) + timedelta(hours=10),
            "estado": "Ingresó" if i % 4 == 0 else "Inscrito", "puntaje": None,
            "fecha_resultado": f if i % 4 == 0 else None,
            "fecha_actualizacion": datetime.combine(f, datetime.min.time()) + timedelta(hours=11),
        })
    df = pd.concat([df, pd.DataFrame(pruebas)], ignore_index=True)
    df = df.sample(frac=1, random_state=int(rng.integers(1e9))).reset_index(drop=True)

    if viejo:
        def fmt(x, hora=True):
            if x is None or pd.isna(x):
                return ""
            return x.strftime("%d/%m/%Y %H:%M") if hora and isinstance(x, datetime) else x.strftime("%d/%m/%Y")
        salida = pd.DataFrame({
            "Codigo": df["codigo_postulante"], "Tipo Doc": df["tipo_documento"],
            "Nro Documento": df["documento_export"], "Apellidos y Nombres": df.apply(_nombre_viejo, axis=1),
            "Celular": df["celular"], "Modalidad": df["modalidad"], "Carrera": df["carrera"],
            "Sede": df["sede"], "Fecha Inscripcion": [fmt(x) for x in df["fecha_inscripcion"]],
            "Estado": df["estado"], "Puntaje": df["puntaje"].map(lambda v: "" if pd.isna(v) else f"{v:.1f}".replace(".", ",")),
            "Fecha Resultado": [fmt(x, False) for x in df["fecha_resultado"]],
            "Fecha Actualizacion": [fmt(x) for x in df["fecha_actualizacion"]],
        })
        salida.to_csv(carpeta / f"admision_inscripciones_{c.codigo}.csv", sep=";", index=False, encoding="cp1252")
    else:
        def iso(x, hora=True):
            if x is None or pd.isna(x):
                return ""
            return x.strftime("%Y-%m-%d %H:%M:%S") if hora and isinstance(x, datetime) else x.strftime("%Y-%m-%d")
        salida = pd.DataFrame({
            "codigo_postulante": df["codigo_postulante"], "tipo_documento": df["tipo_documento"],
            "documento": df["documento_export"], "nombre_completo": df.apply(_nombre_nuevo, axis=1),
            "celular": df["celular"], "modalidad_ingreso": df["modalidad"].map(lambda s: _sin_tildes(s).upper()),
            "carrera": df["carrera"].map(lambda s: _sin_tildes(s).upper()), "sede": df["sede"].str.upper(),
            "fecha_inscripcion": [iso(x) for x in df["fecha_inscripcion"]],
            "estado": df["estado"].map(lambda s: _sin_tildes(s).upper()),
            "puntaje": df["puntaje"].map(lambda v: "" if pd.isna(v) else f"{v:.1f}"),
            "fecha_resultado": [iso(x, False) for x in df["fecha_resultado"]],
            "fecha_actualizacion": [iso(x) for x in df["fecha_actualizacion"]],
        })
        salida.to_csv(carpeta / f"admision_inscripciones_{c.codigo}.csv", index=False, encoding="utf-8")


def _export_crm(c: Campania, sim: dict, rng, carpeta: Path, corte: date | None) -> pd.DataFrame:
    """
    Leads del CRM. Recibe la campaña completa: quien se inscribe después del
    corte pudo registrarse antes como lead. Devuelve el canal de cada persona.
    """
    per = sim["personas"]
    ins = sim["inscripciones"]
    primera = ins.sort_values("fecha_inscripcion").drop_duplicates("id_persona").set_index("id_persona")
    nueva = c.codigo == "2027-1"
    conversion = dict(CONVERSION_CANAL)
    pesos_gen = list(PESO_CANAL["general"])
    if nueva:
        # más presupuesto en redes, que trae leads pero convierte poco
        conversion["Redes sociales"] = 0.042
        pesos_gen = [0.09, 0.13, 0.11, 0.27, 0.15, 0.25]

    leads, canal_persona = [], {}
    for _, p in per.iterrows():
        if rng.random() > 0.82:
            continue
        mod = primera.loc[p["id_persona"], "modalidad"]
        pesos = PESO_CANAL["colegio"] if mod in ("Quinto superior", "Primeros puestos") else pesos_gen
        canal = rng.choice(CANALES, p=np.array(pesos) / sum(pesos))
        canal_persona[p["id_persona"]] = canal
        f_ins = primera.loc[p["id_persona"], "fecha_inscripcion"]
        f = f_ins - timedelta(days=float(rng.gamma(2, 9)))
        piso = datetime.combine(c.inicio - timedelta(days=20), datetime.min.time())
        if f < piso:
            f = piso + (f_ins - piso) * float(rng.random())
        leads.append({"persona": p, "canal": canal, "fecha": f, "carrera": p["carrera"], "sede": p["sede"]})

    # leads que no llegan a inscribirse, según la tasa de cada canal
    convertidos = pd.Series([lead["canal"] for lead in leads]).value_counts()
    perfil = _perfil_diario(c)
    for canal in CANALES:
        n = int(round(convertidos.get(canal, 0) * (1 / conversion[canal] - 1)))
        for _ in range(n):
            d = c.inicio + timedelta(days=int(rng.choice(len(perfil), p=perfil)) - int(rng.integers(0, 20)))
            tipo, doc = "DNI", f"{rng.integers(1, 8)}{rng.integers(0, 10**7):07d}"
            nombre = rng.choice(NOMBRES)
            leads.append({"persona": {"nombres": nombre, "ap_paterno": rng.choice(APELLIDOS),
                                      "ap_materno": rng.choice(APELLIDOS), "documento": doc,
                                      "celular": _celular(rng)},
                          "canal": canal, "fecha": datetime.combine(d, datetime.min.time())
                          + timedelta(hours=int(rng.integers(7, 23))),
                          "carrera": rng.choice(list(CARRERAS)), "sede": rng.choice(list(SEDES), p=list(SEDES.values()))})

    filas = []
    for i, lead in enumerate(sorted(leads, key=lambda x: x["fecha"])):
        p = lead["persona"]
        nombre = f"{p['nombres']} {p['ap_paterno']}"
        nombre = nombre.lower().title() if rng.random() < 0.7 else nombre.upper()
        fila = {
            "ID Lead": f"L{c.codigo.replace('-', '')}-{i + 1:06d}",
            "Fecha de registro": lead["fecha"],
            "Nombre": nombre,
            "Documento": p["documento"] if rng.random() < 0.55 else None,
            "Celular": _celular_crm(p["celular"], rng) if rng.random() < 0.92 else None,
            "Canal": lead["canal"],
            "Carrera de interés": lead["carrera"],
            "Sede de interés": lead["sede"],
        }
        filas.append(fila)
        # la misma persona se registra dos veces (otro formulario, otro día)
        if rng.random() < 0.06:
            filas.append({**fila, "ID Lead": f"L{c.codigo.replace('-', '')}-{i + 1:06d}B",
                          "Fecha de registro": lead["fecha"] + timedelta(days=int(rng.integers(1, 15)))})
    df = pd.DataFrame(filas)
    if corte is not None:
        df = df[df["Fecha de registro"].dt.date <= corte]
    df.to_excel(carpeta / f"crm_interesados_{c.codigo}.xlsx", index=False)
    return pd.Series(canal_persona, name="canal_lead")


def _export_tesoreria(c: Campania, sim: dict, rng, carpeta: Path) -> None:
    per = sim["personas"].set_index("id_persona")
    ins = sim["inscripciones"]
    filas = []

    def doc_tesoreria(doc: str):
        # el sistema de tesorería guarda el documento como número
        return int(doc) if doc.isdigit() else doc

    for _, r in ins.iterrows():
        monto = MODALIDADES[r["modalidad"]][3]
        if monto == 0:
            continue
        p = per.loc[r["id_persona"]]
        filas.append({"Fecha": r["fecha_inscripcion"] + timedelta(minutes=int(rng.integers(5, 90))),
                      "Documento Pagador": doc_tesoreria(p["documento"]),
                      "Pagador": f"{p['ap_paterno']} {p['ap_materno']} {p['nombres']}".upper(),
                      "Concepto": "DERECHO DE ADMISION", "Referencia": r["codigo_postulante"],
                      "Monto": float(monto)})
    for _, m in sim["matriculas"].iterrows():
        p = per.loc[m["id_persona"]]
        if rng.random() < 0.18:
            # paga el apoderado: otro documento, otro nombre
            documento = doc_tesoreria(f"{rng.integers(1, 5)}{rng.integers(0, 10**7):07d}")
            pagador = f"{p['ap_paterno']} {rng.choice(APELLIDOS)} {rng.choice(NOMBRES)}".upper()
        else:
            documento = doc_tesoreria(p["documento"])
            pagador = f"{p['ap_paterno']} {p['ap_materno']} {p['nombres']}".upper()
        u = rng.random()
        if u < 0.15:
            referencia = None
        elif u < 0.23:
            referencia = f" {m['codigo_postulante']} "
        elif u < 0.29:
            referencia = f"COD {m['codigo_postulante']}"
        else:
            referencia = m["codigo_postulante"]
        filas.append({"Fecha": m["fecha_pago"], "Documento Pagador": documento, "Pagador": pagador,
                      "Concepto": f"MATRICULA {c.codigo}", "Referencia": referencia, "Monto": MONTO_MATRICULA})
    # otros conceptos que vienen en el mismo reporte
    for _ in range(int(len(filas) * 0.04)):
        p = per.sample(1, random_state=int(rng.integers(1e9))).iloc[0]
        f = c.inicio + timedelta(days=int(rng.integers(0, (min(c.cierre, CORTE) - c.inicio).days)))
        filas.append({"Fecha": datetime.combine(f, datetime.min.time()) + timedelta(hours=12),
                      "Documento Pagador": doc_tesoreria(p["documento"]),
                      "Pagador": f"{p['ap_paterno']} {p['ap_materno']} {p['nombres']}".upper(),
                      "Concepto": rng.choice(["CONSTANCIA DE INGRESO", "CARNE UNIVERSITARIO"]),
                      "Referencia": None, "Monto": 35.0})
    df = pd.DataFrame(filas).sort_values("Fecha").reset_index(drop=True)
    df.to_excel(carpeta / f"tesoreria_pagos_{c.codigo}.xlsx", index=False)


def _vacantes(c: Campania, sim_completa: dict, escala: float, rng, carpeta: Path) -> None:
    """Admisión fija las vacantes al inicio con lo que espera recibir."""
    ins = sim_completa["inscripciones"]
    ingresos = ins[ins["estado"] == "Ingresó"].drop_duplicates("id_persona")
    esperado = ingresos.groupby(["carrera", "sede"]).size()
    filas = []
    for carrera in CARRERAS:
        for sede in SEDES:
            base = esperado.get((carrera, sede), 1)
            # la meta se puso con la campaña anterior, así que en Lima Norte quedó alta en 2027-1
            factor = rng.uniform(0.92, 1.22) * (1.15 if (c.codigo == "2027-1" and sede == "Lima Norte") else 1)
            vac = max(5, int(round(base * factor / 5) * 5))
            filas.append({"carrera": carrera, "sede": sede, "vacantes": vac})
    pd.DataFrame(filas).to_csv(carpeta / f"vacantes_{c.codigo}.csv", index=False)


def _verdad(c: Campania, sim: dict, canales: pd.Series) -> pd.DataFrame:
    per = sim["personas"][["id_persona", "tipo_documento", "documento", "sede", "carrera", "celular"]].copy()
    ins = sim["inscripciones"]
    validas = ins[ins["estado"] != "Anulado"]
    per["postulo"] = per["id_persona"].isin(validas["id_persona"])
    ingresos = (ins[ins["estado"] == "Ingresó"].sort_values("fecha_resultado").drop_duplicates("id_persona")
                .set_index("id_persona"))
    per["ingreso"] = per["id_persona"].isin(ingresos.index)
    per["modalidad_ingreso"] = per["id_persona"].map(ingresos["modalidad"])
    per["codigo_ingreso"] = per["id_persona"].map(ingresos["codigo_postulante"])
    mat = sim["matriculas"].set_index("id_persona")
    per["matriculado"] = per["id_persona"].isin(mat.index)
    per["fecha_matricula"] = per["id_persona"].map(mat["fecha_pago"])
    per["canal_lead"] = per["id_persona"].map(canales)
    per["campania"] = c.codigo
    return per


def generar(salida: Path = SALIDA_DEFECTO, escala: float = 1.0, seed: int = 15) -> Path:
    """Escribe crudo/<campaña>/ y verdad/<campaña>.parquet bajo `salida`."""
    rng = np.random.default_rng(seed)
    docs = Documentos(rng)
    salida = Path(salida)
    for c in CAMPANIAS:
        carpeta = salida / "crudo" / c.codigo
        carpeta.mkdir(parents=True, exist_ok=True)
        completa = _simular_campania(c, escala, rng, docs)
        corte = CORTE if c.cierre > CORTE else None
        sim = _aplicar_corte(completa, corte) if corte else completa
        _export_admision(c, sim, rng, carpeta)
        canales = _export_crm(c, completa, rng, carpeta, corte)
        _export_tesoreria(c, sim, rng, carpeta)
        _vacantes(c, completa, escala, rng, carpeta)
        (salida / "verdad").mkdir(exist_ok=True)
        _verdad(c, sim, canales).to_parquet(salida / "verdad" / f"{c.codigo}.parquet", index=False)
        if corte:
            # cómo termina la campaña en curso: solo para revisar la proyección de vacantes
            _verdad(c, completa, canales).to_parquet(salida / "verdad" / f"{c.codigo}_cierre.parquet", index=False)
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=SALIDA_DEFECTO)
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=15)
    a = ap.parse_args()
    print(f"Datos en {generar(a.salida, a.escala, a.seed)}")
