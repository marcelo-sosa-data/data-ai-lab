from reclamos.permisos import PERFILES, Control


def control(perfil="asistente_reclamos"):
    return Control(PERFILES[perfil], id_reclamo=7, id_cliente=120)


def test_el_modelo_solo_ve_su_perfil():
    catalogo = [{"name": n} for n in ("ver_cliente", "emitir_abono", "bloquear_tarjeta")]
    assert [h["name"] for h in control().visibles(catalogo)] == ["ver_cliente", "emitir_abono"]
    assert [h["name"] for h in control("revision_humana").visibles(catalogo)] == ["ver_cliente"]


def test_alcance_del_reclamo():
    c = control()
    assert not c.autorizar("ver_cliente", {"id_cliente": 121}).permitido
    assert not c.autorizar("derivar_reclamo", {"id_reclamo": 8, "area": "x", "resumen": ""}).permitido
    assert c.autorizar("ver_cliente", {"id_cliente": "120"}).permitido


def test_solo_se_actua_sobre_movimientos_vistos():
    c = control()
    assert not c.autorizar("revisar_cargo", {"id_movimiento": 500}).permitido
    c.registrar_salida("listar_movimientos", {"movimientos": [{"id_movimiento": 500}]}, False)
    assert c.autorizar("revisar_cargo", {"id_movimiento": 500}).permitido
    abono = {"id_reclamo": 7, "id_movimiento": 500, "monto": 80.0, "motivo": "cargo_duplicado"}
    assert c.autorizar("emitir_abono", abono).permitido
    c.registrar_salida("emitir_abono", {}, False)
    d = c.autorizar("emitir_abono", abono)
    assert not d.permitido and "Ya hay un abono" in d.razon


def test_tope_del_perfil_y_maximo_de_llamadas():
    c = control()
    c.registrar_salida("listar_movimientos", {"movimientos": [{"id_movimiento": 9}]}, False)
    d = c.autorizar("emitir_abono", {"id_reclamo": 7, "id_movimiento": 9, "monto": 720, "motivo": "cargo_duplicado"})
    assert not d.permitido and "tope" in d.razon
    for _ in range(PERFILES["asistente_reclamos"].max_llamadas):
        c.autorizar("ver_cliente", {"id_cliente": 120})
    assert "máximo" in c.autorizar("ver_cliente", {"id_cliente": 120}).razon
    assert sum(not d.permitido for d in c.decisiones) == 2
