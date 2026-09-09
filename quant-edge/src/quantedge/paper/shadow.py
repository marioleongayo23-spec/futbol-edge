"""Paper trading SHADOW_ONLY sobre sesiones futuras (holdout oculto).

Regla dura del encargo: TODAS las operaciones son SHADOW_ONLY. Este módulo
simula, sesión a sesión, las órdenes que el modelo congelado emitiría, calcula
su resultado neto y las registra en un libro en sombra. NUNCA cambia beta ni
capital real; el modo va sellado en cada registro y se verifica en la puerta.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..backtest.engine import run_backtest
from ..costs.model import InstrumentCosts
from ..strategies.base import Strategy

SHADOW_MODE = "SHADOW_ONLY"


@dataclass
class ShadowResult:
    sessions: pd.DataFrame
    returns: pd.Series
    n_sessions: int
    mode: str = SHADOW_MODE

    def all_shadow(self) -> bool:
        return bool((self.sessions["mode"] == SHADOW_MODE).all())


def run_shadow(df_future: pd.DataFrame, strategy: Strategy, costs: InstrumentCosts,
               instrument: str = "") -> ShadowResult:
    """Ejecuta el modelo congelado en modo sombra sobre datos no vistos."""
    bt = run_backtest(df_future, strategy, costs)
    target = strategy.signal(df_future).shift(costs.latency_bars)
    sessions = pd.DataFrame(
        {
            "date": df_future.index,
            "instrument": instrument,
            "strategy": strategy.key(),
            "target_weight": target.to_numpy(),
            "executed_weight": bt.weights.to_numpy(),
            "session_return": bt.net_returns_after_tax.to_numpy(),
            "mode": SHADOW_MODE,
        }
    )
    return ShadowResult(
        sessions=sessions,
        returns=bt.net_returns_after_tax,
        n_sessions=len(df_future),
    )
