import numpy as np

from quantedge.validation.bootstrap import bootstrap_ci, monte_carlo
from quantedge.validation.metrics import geometric_mean
from quantedge.validation.multiple_testing import (
    benjamini_hochberg,
    bonferroni,
    pbo_cscv,
)


def test_bootstrap_ci_brackets_point():
    r = np.random.default_rng(0).normal(0.0005, 0.01, 500)
    ci = bootstrap_ci(r, geometric_mean, n_boot=500, seed=1)
    assert ci.lo <= ci.point <= ci.hi


def test_monte_carlo_probabilities_bounded():
    r = np.random.default_rng(2).normal(0.0005, 0.01, 500)
    mc = monte_carlo(r, n_paths=500, target_daily=0.004)
    assert 0.0 <= mc.prob_hit_target <= 1.0
    assert 0.0 <= mc.prob_positive <= 1.0


def test_pbo_high_for_pure_noise():
    # N estrategias de puro ruido: la mejor en muestra no debería sobrevivir OOS.
    rng = np.random.default_rng(7)
    mat = rng.normal(0.0, 0.01, size=(600, 12))
    out = pbo_cscv(mat, n_groups=10)
    assert 0.0 <= out["pbo"] <= 1.0
    assert out["pbo"] > 0.2  # sobreajuste alto esperado en ruido


def test_bonferroni_and_bh():
    p = np.array([0.001, 0.02, 0.2, 0.5])
    assert np.all(bonferroni(p) >= p)
    bh = benjamini_hochberg(p, alpha=0.05)
    assert bh["n_rejected"] >= 1
