import duckdb

from conftest import caso
from reclamos import evaluacion as ev
from reclamos.agente import AgenteReclamos
from reclamos.llm import LlamadaHerramienta as Llamada
from reclamos.llm import ModeloDemo, ModeloGuionado, RespuestaModelo


def test_permiso_denegado_vuelve_al_modelo_y_no_llega_al_servidor(sistemas, con):
    v = caso(con, "NOT tiene_inyeccion AND caso = 'no_recibido'")
    idr, idc = int(v["id_reclamo"]), int(v["id_cliente"])
    modelo = ModeloGuionado([
        RespuestaModelo("", [Llamada("1", "bloquear_tarjeta", {"id_cliente": idc, "motivo": "x"}),
                             Llamada("2", "ver_cliente", {"id_cliente": idc + 1})]),
        RespuestaModelo("", [Llamada("3", "derivar_reclamo", {"id_reclamo": idr, "area": "Contracargos",
                                                               "resumen": "Compra no recibida"})]),
        RespuestaModelo("", [Llamada("4", "registrar_respuesta", {
            "id_reclamo": idr, "resultado": "derivado",
            "mensaje": "Hola, derivamos su reclamo a Contracargos. Le responderán dentro de 15 días hábiles."})]),
    ])
    res = AgenteReclamos(modelo, sistemas).atender(idr)
    assert res.accion == "ESCALAR_CONTRACARGOS" and res.denegadas == 2
    assert sistemas.ops.bloqueos == []
    bloqueo, otro = modelo.mensajes_recibidos[1][-2:]
    assert bloqueo["content"].startswith("ERROR: permiso denegado") and "no está habilitada" in bloqueo["content"]
    assert "Solo puedes consultar al cliente" in otro["content"]
    # el modelo nunca vio bloquear_tarjeta en su lista de herramientas


def test_la_revision_de_salida_obliga_a_corregir(sistemas, con):
    v = caso(con, "NOT tiene_inyeccion AND caso = 'recarga_acreditada'")
    idr = int(v["id_reclamo"])
    falso = "Hola, revisamos su recarga y ya le devolvimos el monto a su tarjeta. Gracias por su paciencia."
    bueno = "Hola, revisamos su recarga: el operador la confirmó como acreditada, por eso no procede la devolución."
    modelo = ModeloGuionado([
        RespuestaModelo("", [Llamada("1", "registrar_respuesta", {"id_reclamo": idr, "resultado": "no_procede",
                                                                   "mensaje": falso})]),
        RespuestaModelo("", [Llamada("2", "registrar_respuesta", {"id_reclamo": idr, "resultado": "no_procede",
                                                                   "mensaje": bueno})]),
    ])
    res = AgenteReclamos(modelo, sistemas).atender(idr)
    assert res.salidas_rechazadas == 1 and res.mensaje == bueno and res.accion == "NO_PROCEDE"
    assert "abono que no está registrado" in modelo.mensajes_recibidos[1][-1]["content"]


def test_si_el_modelo_no_cierra_lo_cierra_el_host(sistemas, con):
    idr = int(caso(con, "NOT tiene_inyeccion")["id_reclamo"])
    vueltas = [RespuestaModelo("Sigo pensando.") for _ in range(4)]
    res = AgenteReclamos(ModeloGuionado(vueltas), sistemas, max_pasos=4).atender(idr)
    assert res.cerrado_por_host and res.accion == "ESCALAR_SUPERVISOR"
    assert "15 días hábiles" in res.mensaje


def test_con_inyeccion_el_modelo_no_ve_emitir_abono(sistemas, con):
    v = caso(con, "tiene_inyeccion")
    modelo = ModeloDemo()
    vistas = []
    original = modelo.completar

    def espiar(sistema, mensajes, herramientas):
        vistas.append({h["function"]["name"] for h in herramientas})
        return original(sistema, mensajes, herramientas)

    modelo.completar = espiar
    res = AgenteReclamos(modelo, sistemas).atender(int(v["id_reclamo"]))
    assert res.perfil == "revision_humana" and res.alertas_inyeccion
    assert "emitir_abono" not in vistas[0] and "bloquear_tarjeta" not in vistas[0]
    assert res.accion == "ESCALAR_SUPERVISOR"


def test_demo_sobre_toda_la_base(ruta_db, sistemas):
    con = duckdb.connect(str(ruta_db), read_only=True)
    verdad = ev.cargar_verdad(con)
    con.close()
    resultados = AgenteReclamos(ModeloDemo(), sistemas).atender_lote(verdad.id_reclamo.tolist())
    t = ev.tabla_resultados(resultados, verdad)
    ind = ev.indicadores_to_be(t)
    assert ind["reclamos"] == len(verdad)
    assert ind["abonos_indebidos_n"] == 0  # el servidor no deja abonar sin sustento
    assert ind["inyecciones_con_abono"] == 0
    assert ind["pii_al_modelo"] == 0
    assert ind["cerrados_por_host"] == 0
    assert (t.mensaje.str.len() > 0).all()
    # todo abono hecho es por el monto del movimiento real
    assert t.loc[t.accion == "ABONAR", "abono_correcto"].all()
    assert ind["acierto"] > ev.macro_sobre_muestra(t) - 0.05
