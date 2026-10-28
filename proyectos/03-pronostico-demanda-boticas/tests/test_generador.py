import duckdb
import numpy as np
import pandas as pd

from generar_datos import generar


def test_reproducible_con_la_misma_semilla(tmp_path, base):
    otra = generar(tmp_path / "otra.duckdb", escala=0.25, seed=7)
    con = duckdb.connect(str(otra), read_only=True)
    total = con.execute("SELECT SUM(unidades), SUM(stock_cierre) FROM ventas_diarias").fetchone()
    con.close()
    assert total == (base.ventas.unidades.sum(), base.ventas.stock_cierre.sum())


def test_venta_nunca_supera_la_demanda_y_solo_se_corta_con_quiebre(base):
    m = base.ventas.merge(base.latente, on=["fecha", "id_local", "id_producto"])
    assert (m.unidades <= m.demanda).all()
    con_stock = m[m.stock_cierre > 0]
    assert (con_stock.unidades == con_stock.demanda).all()


def test_balance_de_stock(base):
    v = base.ventas.sort_values(["id_local", "id_producto", "fecha"])
    previo = v.groupby(["id_local", "id_producto"]).stock_cierre.shift()
    ok = previo.notna()
    esperado = previo[ok] + v.unidades_recibidas[ok] - v.unidades[ok]
    assert (esperado == v.stock_cierre[ok]).all()


def _demanda(base, filtro_prod, filtro_loc, desde, hasta):
    m = (base.latente.merge(base.productos, on="id_producto")
         .merge(base.locales.drop(columns="nombre"), on="id_local"))
    m = m[filtro_prod(m) & filtro_loc(m) & m.fecha.between(desde, hasta)]
    return m.groupby("fecha").demanda.sum().mean()


def test_invierno_en_lima(base):
    resp = lambda m: m.categoria == "Respiratorio"  # noqa: E731
    lima = lambda m: m.region == "Lima"  # noqa: E731
    julio = _demanda(base, resp, lima, "2025-07-01", "2025-07-31")
    febrero = _demanda(base, resp, lima, "2025-02-01", "2025-02-28")
    assert julio > 1.6 * febrero


def test_dengue_sube_paracetamol_y_no_ibuprofeno_en_el_norte(base):
    norte = lambda m: m.region == "Norte"  # noqa: E731
    para = lambda m: m.nombre.str.startswith("Paracetamol 500")  # noqa: E731
    pico = _demanda(base, para, norte, "2024-04-01", "2024-04-15")
    normal = _demanda(base, para, norte, "2024-09-01", "2024-09-15")
    assert pico > 1.5 * normal
    # ibuprofeno no está en la base chica; se revisa en el catálogo que no tenga sensibilidad
    from generar_datos import PRODUCTOS
    sens = {p[0]: p[6] for p in PRODUCTOS}
    assert sens["Ibuprofeno 400 mg x 10 tab"] == 0


def test_local_nuevo_sin_filas_antes_de_abrir(base):
    nuevo = base.locales[base.locales.nombre == "Alameda Carabayllo"].iloc[0]
    v = base.ventas[base.ventas.id_local == nuevo.id_local]
    assert v.fecha.min() == pd.Timestamp(nuevo.apertura)


def test_quiebres_mas_frecuentes_cuando_la_demanda_sube(base):
    # el promedio de 28 días se queda atrás en la subida del invierno
    m = base.ventas.merge(base.productos, on="id_producto").merge(base.locales, on="id_local")
    resp = m[(m.categoria == "Respiratorio") & (m.region == "Lima")]
    subida = resp[resp.fecha.between("2025-06-01", "2025-07-15")].stock_cierre.eq(0).mean()
    bajada = resp[resp.fecha.between("2025-08-15", "2025-09-30")].stock_cierre.eq(0).mean()
    assert subida > 2 * bajada
    assert np.isfinite(subida)
