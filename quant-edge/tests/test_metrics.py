import numpy as np
import pandas as pd

from quantedge.validation.metrics import (
    deflated_sharpe_ratio,
    geometric_mean,
    max_drawdown,
    monthly_geometric_daily_mean,
    probabilistic_sharpe_ratio,
    summarize,
)


def test_geometric_mean_constant():
    r = np.full(100, 0.01)
    assert abs(geometric_mean(r) - 0.01) < 1e-12


def test_geometric_mean_offsetting():
    # +10% seguido de -9.0909% vuelve al inicio -> media geométrica ~ 0.
    r = np.array([0.10, -0.10 / 1.10])
    assert abs(geometric_mean(r)) < 1e-12


def test_monthly_grouping():
    idx = pd.date_range("2021-01-01", periods=60, freq="B")
    r = pd.Series(np.full(60, 0.002), index=idx)
    monthly = monthly_geometric_daily_mean(r)
    assert len(monthly) >= 2
    assert np.allclose(monthly.to_numpy(), 0.002, atol=1e-9)


def test_max_drawdown_known():
    r = pd.Series([0.0, -0.2, 0.0, 0.0])  # cae 20%
    assert abs(max_drawdown(r) - 0.2) < 1e-9


def test_psr_monotonic_in_sharpe():
    rng = np.random.default_rng(0)
    weak = rng.normal(0.0002, 0.01, 500)
    strong = rng.normal(0.002, 0.01, 500)
    assert probabilistic_sharpe_ratio(strong) > probabilistic_sharpe_ratio(weak)


def test_dsr_penalizes_many_trials():
    rng = np.random.default_rng(1)
    r = rng.normal(0.001, 0.01, 800)
    few = deflated_sharpe_ratio(r, n_trials=2, sr_variance=0.001)
    many = deflated_sharpe_ratio(r, n_trials=500, sr_variance=0.001)
    assert many <= few  # más pruebas -> más difícil ser significativo


def test_summarize_keys():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    r = pd.Series(np.random.default_rng(3).normal(0.0005, 0.01, 300), index=idx)
    s = summarize(r).to_dict()
    for k in ("geo_daily_mean", "monthly_geo_daily_mean_median", "max_drawdown", "psr"):
        assert k in s
