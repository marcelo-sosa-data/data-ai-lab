import numpy as np

from elasticidad import modelo as M


def test_rasgos_rezagos_y_descuento(m):
    meta = M.Meta.desde(m)
    r = M.rasgos(meta, m.semanas, m.precio, m.regular, m.encarte)
    regular = np.isclose(m.precio, m.regular)
    assert np.allclose(r["ld"][regular], 0)
    assert (r["ld"][~regular] < 0).all()
    prof = 1 - m.precio / m.regular
    assert np.allclose(r["p1"][1:], prof[:-1]) and np.allclose(r["p2"][2:], prof[:-2])
    # el índice de precio regular queda centrado en el ajuste
    assert np.allclose(r["lr"].mean(0), 0, atol=1e-9)


def test_prediccion_en_numpy_igual_a_pymc(m):
    meta = M.Meta.desde(m)
    modelo = M.construir(m, meta, con_mu=True)
    rng = np.random.default_rng(0)
    punto = {k: v + rng.normal(0, 0.3, size=v.shape) for k, v in modelo.initial_point().items()}
    nombres = [k for k in M.PARAMETROS if k != "alpha"]
    f = modelo.compile_fn([modelo["eta"]] + [modelo[k] for k in nombres], inputs=modelo.value_vars,
                          point_fn=False, on_unused_input="ignore")
    eta_pymc, *valores = f(**punto)
    post = {k: np.asarray(v)[None] for k, v in zip(nombres, valores)}
    r = M.rasgos(meta, m.semanas, m.precio, m.regular, m.encarte)
    eta_np = M.log_mu(post, r, meta, idx_t=np.arange(2, len(m.semanas)))[0]
    assert np.allclose(eta_np, eta_pymc, atol=1e-8)


def test_ajuste_corto_ordena_las_categorias(ajuste, m):
    post, meta, diag = ajuste
    mu = dict(zip(meta.categorias, post["mu_e"].mean(0)))
    assert all(v < 0 for v in mu.values())
    assert mu["Arroz"] > mu["Gaseosas"]            # el arroz es mucho menos sensible al precio
    assert post["cruz"].mean(0).min() > 0          # las marcas se sustituyen
    assert post["post1"].mean(0)[meta.categorias.index("Detergentes")] < -0.5   # se almacena


def test_guardar_y_cargar(ajuste, tmp_path):
    post, meta, diag = ajuste
    M.guardar(tmp_path, "x", post, meta, diag)
    post2, meta2, diag2 = M.cargar(tmp_path, "x")
    assert meta2 == meta and diag2 == diag
    assert all(np.array_equal(post[k], post2[k]) for k in post)
