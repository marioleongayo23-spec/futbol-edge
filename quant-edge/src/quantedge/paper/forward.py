"""Paper trading FORWARD en modo SHADOW_ONLY, con libro persistente.

Flujo previsto en vivo:
  1. Se congela el modelo (`model.frozen.FrozenModel`) tras el estudio.
  2. Cada sesión nueva llega (día t). Con datos SOLO hasta t-1 se decide la orden
     en sombra; cuando se cierra el día t se registra el retorno neto realizado.
  3. El libro (`ForwardLedger`, JSONL append-only) acumula sesiones. Cuando hay
     >=60 sesiones se puede pasar la puerta forward.

`replay_forward` hace un ENSAYO EN SECO reproduciendo un tramo histórico
(holdout) sesión a sesión — marcado `is_live=False`, por lo que NUNCA satisface
la condición 14 (sesiones en vivo). Sirve para probar el bucle y el libro sin red.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..backtest.engine import run_backtest
from ..costs.model import InstrumentCosts
from ..gate.evaluate import GateInput, GateResult, evaluate_gate
from ..model.frozen import FrozenModel
from ..strategies.base import Strategy
from ..validation.metrics import geometric_mean, summarize

SHADOW_MODE = "SHADOW_ONLY"


class ForwardLedger:
    """Libro append-only de sesiones forward en sombra (JSONL)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        record = {**record, "mode": SHADOW_MODE}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def frame(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=["date", "instrument", "session_return", "mode", "is_live"])
        rows = [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def portfolio_returns(self) -> pd.Series:
        df = self.frame()
        if df.empty:
            return pd.Series(dtype=float)
        wide = df.pivot_table(index="date", columns="instrument", values="session_return", aggfunc="mean")
        return wide.mean(axis=1, skipna=True).dropna().sort_index()

    def all_shadow(self) -> bool:
        df = self.frame()
        return bool(df.empty or (df["mode"] == SHADOW_MODE).all())

    def is_live(self) -> bool:
        df = self.frame()
        return bool(not df.empty and df.get("is_live", pd.Series([False])).all())


@dataclass
class ForwardRunner:
    """Ejecutor incremental para uso en vivo (una sesión por instrumento y día)."""

    frozen: FrozenModel
    ledger: ForwardLedger

    def step(self, instrument: str, bars_until_today: pd.DataFrame, realized_return: float,
             session_date, is_live: bool = True) -> None:
        """Registra la sesión del día. `bars_until_today` = datos hasta el cierre
        de la sesión (para calcular la señal causal); `realized_return` = retorno
        neto realizado de esa sesión en sombra."""
        strat = self.frozen.strategy_for(instrument)
        costs = self.frozen.instrument_costs()
        target = strat.signal(bars_until_today).shift(costs.latency_bars)
        tw = float(target.iloc[-1]) if len(target) and pd.notna(target.iloc[-1]) else 0.0
        self.ledger.append({
            "date": pd.Timestamp(session_date).isoformat(),
            "instrument": instrument,
            "strategy": strat.key(),
            "target_weight": tw,
            "session_return": float(realized_return),
            "is_live": bool(is_live),
        })


def replay_forward(frozen: FrozenModel, data_by_instrument: dict[str, pd.DataFrame],
                   holdout_dates: pd.DatetimeIndex, ledger: ForwardLedger) -> None:
    """Ensayo en seco: reproduce el holdout sesión a sesión (is_live=False)."""
    for instrument, df in data_by_instrument.items():
        if instrument not in frozen.instruments:
            continue
        strat = frozen.strategy_for(instrument)
        costs = frozen.instrument_costs()
        end = df.index.get_indexer([holdout_dates[-1]])[0]
        prefix = df.iloc[: end + 1]
        bt = run_backtest(prefix, strat, costs)
        target = strat.signal(prefix).shift(costs.latency_bars)
        rets = bt.net_returns_after_tax.reindex(holdout_dates)
        tw = target.reindex(holdout_dates)
        for d in holdout_dates:
            if pd.isna(rets.get(d)):
                continue
            ledger.append({
                "date": pd.Timestamp(d).isoformat(),
                "instrument": instrument,
                "strategy": strat.key(),
                "target_weight": float(tw.get(d)) if pd.notna(tw.get(d)) else 0.0,
                "session_return": float(rets.get(d)),
                "is_live": False,
            })


def combined_gate(ledger: ForwardLedger, dev_robustness: dict, thresholds: dict,
                  benchmark_geo_daily: float) -> GateResult:
    """Evalúa la puerta completa combinando robustez de desarrollo (DSR/PBO/
    multi-mercado, del estudio congelado) con el rendimiento FORWARD acumulado."""
    port = ledger.portfolio_returns()
    s = summarize(port, thresholds.get("target_daily", 0.004))
    # dependencia de mes extremo sobre forward
    if len(port):
        import numpy as np
        periods = port.index.to_period("M")
        month_log = port.groupby(periods).apply(lambda x: float(np.sum(np.log1p(x.to_numpy()))))
        total = float(month_log.sum())
        max_share = float(month_log.max() / total) if total > 0 else float("inf")
        best = month_log.idxmax()
        geo_ex = geometric_mean(port[periods != best].to_numpy())
    else:
        max_share, geo_ex = float("inf"), float("nan")

    gi = GateInput(
        oos_monthly_geo_daily_mean_mean=s.monthly_geo_daily_mean_mean,
        oos_monthly_geo_daily_mean_median=s.monthly_geo_daily_mean_median,
        oos_max_drawdown=s.max_drawdown,
        oos_geo_daily_mean=s.geo_daily_mean,
        benchmark_geo_daily_mean=benchmark_geo_daily,
        deflated_sharpe=dev_robustness.get("deflated_sharpe", 0.0),
        pbo=dev_robustness.get("pbo", 1.0),
        bootstrap_geo_daily_lb=dev_robustness.get("bootstrap_geo_daily_lb", -1.0),
        n_markets_total=dev_robustness.get("n_markets_total", 0),
        n_markets_meeting_target=dev_robustness.get("n_markets_meeting_target", 0),
        max_single_month_share=max_share,
        geo_daily_leave_best_out=geo_ex,
        cost_stress=dev_robustness.get("cost_stress", {}),
        n_future_sessions=int(port.shape[0]),
        all_shadow_only=ledger.all_shadow(),
        data_is_real_dual_source=dev_robustness.get("data_is_real_dual_source", False),
        forward_sessions_are_live=ledger.is_live(),
    )
    return evaluate_gate(gi, thresholds)
