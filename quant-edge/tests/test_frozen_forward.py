import numpy as np
import pandas as pd

from quantedge.costs.model import InstrumentCosts
from quantedge.model.frozen import FrozenModel, freeze_from_selection
from quantedge.paper.forward import ForwardLedger, combined_gate, replay_forward
from quantedge.strategies.library import Momentum, make_strategy
from quantedge.validation.resample import bars_frequency, intraday_returns_to_daily


def _df(n=400, seed=0):
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    mid = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    return pd.DataFrame(
        {"mid": mid, "bid": mid * 0.999, "ask": mid * 1.001,
         "volume_value": np.full(n, 1e12), "sigma_bar": np.full(n, 0.01),
         "spread_bps": np.full(n, 2.0)}, index=idx)


def test_frozen_model_roundtrip(tmp_path):
    sel = {"A": Momentum(lookback=42), "B": Momentum(lookback=126)}
    fm = freeze_from_selection(sel, InstrumentCosts(), {"target_daily": 0.004},
                               {"A": "h1", "B": "h2"}, "params_hash")
    path = fm.save(tmp_path / "m.json")
    loaded = FrozenModel.load(path)
    s = loaded.strategy_for("A")
    assert s.name == "momentum" and s.params["lookback"] == 42
    assert isinstance(loaded.instrument_costs(), InstrumentCosts)


def test_make_strategy_unknown_raises():
    try:
        make_strategy("no_existe")
        assert False
    except KeyError:
        pass


def test_replay_forward_and_gate(tmp_path):
    data = {"A": _df(seed=1), "B": _df(seed=2)}
    sel = {"A": Momentum(lookback=42), "B": Momentum(lookback=63)}
    fm = freeze_from_selection(sel, InstrumentCosts(), {"target_daily": 0.004},
                               {"A": "h", "B": "h"}, "p")
    holdout = data["A"].index[-120:]
    ledger = ForwardLedger(tmp_path / "led.jsonl")
    replay_forward(fm, data, holdout, ledger)
    port = ledger.portfolio_returns()
    assert len(port) > 0
    assert ledger.all_shadow() is True
    assert ledger.is_live() is False  # ensayo en seco
    res = combined_gate(ledger, {"deflated_sharpe": 0.99, "pbo": 0.1,
                                 "bootstrap_geo_daily_lb": 0.001,
                                 "n_markets_total": 3, "n_markets_meeting_target": 3,
                                 "cost_stress": {"1.0": 0.005}, "data_is_real_dual_source": True},
                        {"target_daily": 0.004, "min_future_sessions": 60}, benchmark_geo_daily=0.0)
    # Aunque la robustez fuese buena, is_live=False bloquea -> NO DEMOSTRADO.
    assert res.decision == "NO DEMOSTRADO"
    assert any("en_vivo" in m for m in res.missing_evidence)


def test_intraday_to_daily():
    idx = pd.to_datetime(["2022-01-03 09:30", "2022-01-03 15:30",
                          "2022-01-04 09:30", "2022-01-04 15:30"])
    r = pd.Series([0.01, 0.01, -0.02, 0.0], index=idx)
    daily = intraday_returns_to_daily(r)
    assert len(daily) == 2
    assert np.isclose(daily.iloc[0], (1.01 * 1.01) - 1)
    assert bars_frequency(idx) == "intraday"
