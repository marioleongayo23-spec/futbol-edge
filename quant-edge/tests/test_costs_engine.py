import numpy as np
import pandas as pd

from quantedge.backtest.engine import run_backtest
from quantedge.costs.model import InstrumentCosts, cost_of_trade
from quantedge.strategies.base import Strategy


def test_cost_monotonic_in_size():
    ic = InstrumentCosts()
    small = cost_of_trade(ic, 1e5, 0.015, 1e12).total
    big = cost_of_trade(ic, 1e6, 0.015, 1e12).total
    assert big > small


def test_partial_fill_caps_execution():
    ic = InstrumentCosts(max_participation=0.05)
    tc = cost_of_trade(ic, trade_notional=1e9, sigma_bar=0.02, bar_volume_value=1e9)
    assert tc.executed_notional <= 0.05 * 1e9 + 1e-6
    assert tc.unfilled_notional > 0


def _flat_df(n=50, price=100.0):
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {
            "mid": np.full(n, price),
            "bid": np.full(n, price - 0.01),
            "ask": np.full(n, price + 0.01),
            "volume_value": np.full(n, 1e12),
            "sigma_bar": np.full(n, 0.01),
            "spread_bps": np.full(n, 2.0),
        },
        index=idx,
    )


class OneDayLong(Strategy):
    name = "oneday"

    def signal(self, df):
        s = pd.Series(0.0, index=df.index)
        s.iloc[10] = 1.0  # sólo pide estar largo en la barra 10
        return s


def test_no_lookahead_shift():
    # Con precio plano, ningún retorno; verificamos que el peso EFECTIVO se
    # activa después de la señal (latencia por defecto 1 -> desfase 1+1=2).
    df = _flat_df()
    ic = InstrumentCosts(latency_bars=1)
    bt = run_backtest(df, OneDayLong(), ic, apply_tax=False)
    w = bt.weights
    # La señal está en la barra 10; el peso heredado no puede activarse antes.
    assert w.iloc[:12].abs().sum() == 0.0 or w.index[w.abs() > 0][0] > df.index[10]


class AlwaysLong(Strategy):
    name = "always"

    def signal(self, df):
        return pd.Series(1.0, index=df.index)


def test_buy_and_hold_tracks_asset_minus_costs():
    n = 260
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rng = np.random.default_rng(5)
    ret = rng.normal(0.0004, 0.01, n)
    mid = 100 * np.cumprod(1 + ret)
    df = pd.DataFrame(
        {"mid": mid, "bid": mid * 0.9999, "ask": mid * 1.0001,
         "volume_value": np.full(n, 1e13), "sigma_bar": np.full(n, 0.01),
         "spread_bps": np.full(n, 1.0)},
        index=idx,
    )
    ic = InstrumentCosts(commission_bps=0.1, half_spread_bps=0.1, slippage_coef=0.0,
                         impact_coef=0.0, latency_bars=0, tax_rate=0.0)
    bt = run_backtest(df, AlwaysLong(), ic, apply_tax=False)
    asset_total = mid[-1] / mid[0] - 1
    strat_total = bt.equity(after_tax=False).iloc[-1] - 1
    # Debe seguir al activo salvo un pequeño coste de entrada.
    assert abs(strat_total - asset_total) < 0.01
