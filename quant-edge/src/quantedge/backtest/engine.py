"""Motor de backtest largo/plano con costes, latencia y fills parciales.

Convención sin look-ahead:
  - Durante la barra t se mantiene el peso `w` heredado y se gana `w · ret[t]`.
  - Al cierre de t se rebalancea hacia el objetivo decidido en t-(1+latencia),
    pagando costes; ese peso se mantiene en la barra siguiente.
  - El fill es parcial: no se puede mover más nocional que
    `max_participation · volumen_barra`; el resto se completa en barras futuras.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..costs.model import InstrumentCosts, apply_annual_taxes, cost_of_trade
from ..strategies.base import Strategy


@dataclass
class BacktestResult:
    net_returns: pd.Series            # tras costes, antes de impuestos
    net_returns_after_tax: pd.Series  # tras costes e impuestos
    gross_returns: pd.Series
    weights: pd.Series
    turnover: pd.Series
    cost_drag: pd.Series
    trades: pd.DataFrame

    def equity(self, after_tax: bool = True) -> pd.Series:
        r = self.net_returns_after_tax if after_tax else self.net_returns
        return (1.0 + r.fillna(0.0)).cumprod()


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    costs: InstrumentCosts,
    capital0: float = 1_000_000.0,
    apply_tax: bool = True,
) -> BacktestResult:
    target = strategy.signal(df).clip(0.0, 1.0)
    # El bucle ya impone un retardo estructural de 1 barra (se decide al cierre
    # de t y se mantiene en t+1). `latency_bars` añade el retardo EXTRA de
    # ejecución. Con latency=0, el peso de la barra t es signal[t-1] (sin
    # look-ahead, backtest estándar con desfase de 1 día).
    target_exec = target.shift(costs.latency_bars)
    ret = df["mid"].pct_change()

    mids = df["mid"].to_numpy()
    vols = df["volume_value"].to_numpy()
    sig = df["sigma_bar"].to_numpy()
    tgt = target_exec.to_numpy()
    r = ret.to_numpy()
    n = len(df)

    V = capital0
    w = 0.0
    weights = np.zeros(n)
    turns = np.zeros(n)
    cost_drag = np.zeros(n)
    grets = np.zeros(n)
    nrets = np.zeros(n)
    trade_rows = []

    for t in range(n):
        rt = r[t] if np.isfinite(r[t]) else 0.0
        g = w * rt  # P&L de la barra con el peso heredado
        desired = tgt[t]
        if not np.isfinite(desired):
            desired = w
        dw = desired - w
        trade_notional = dw * V
        if abs(trade_notional) > 0:
            tc = cost_of_trade(costs, trade_notional, sig[t], vols[t])
            exec_dw = np.sign(dw) * (tc.executed_notional / V if V > 0 else 0.0)
            cost_ret = tc.total / V if V > 0 else 0.0
            if tc.executed_notional > 0:
                trade_rows.append(
                    {
                        "date": df.index[t],
                        "delta_w": exec_dw,
                        "executed_notional": tc.executed_notional,
                        "unfilled_notional": tc.unfilled_notional,
                        "commission": tc.commission,
                        "spread": tc.spread,
                        "slippage": tc.slippage,
                        "impact": tc.impact,
                        "cost_total": tc.total,
                    }
                )
        else:
            exec_dw = 0.0
            cost_ret = 0.0
        net = g - cost_ret
        w_new = w + exec_dw
        V *= 1.0 + net

        weights[t] = w
        turns[t] = abs(exec_dw)
        cost_drag[t] = cost_ret
        grets[t] = g
        nrets[t] = net
        w = w_new

    idx = df.index
    net_returns = pd.Series(nrets, index=idx)
    if apply_tax:
        net_after_tax = apply_annual_taxes(net_returns, idx, costs.tax_rate)
    else:
        net_after_tax = net_returns.copy()
    trades = pd.DataFrame(trade_rows)
    return BacktestResult(
        net_returns=net_returns,
        net_returns_after_tax=net_after_tax,
        gross_returns=pd.Series(grets, index=idx),
        weights=pd.Series(weights, index=idx),
        turnover=pd.Series(turns, index=idx),
        cost_drag=pd.Series(cost_drag, index=idx),
        trades=trades,
    )
