"""Biblioteca de señales simples y honestas (largo/plano, sin look-ahead).

Familias: momentum, tendencia (cruce de medias), reversión (z-score), ruptura
(Donchian) y momentum escalado por volatilidad. Deliberadamente sencillas: el
objetivo del estudio no es rebuscar una señal exótica sino medir con rigor si
ALGUNA aporta ventaja neta fuera de muestra.

Todas las señales usan rolling windows que terminan en t; el motor aplica luego
el desfase (1 + latencia) para que la señal en t nunca use el retorno de t.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd

from .base import Strategy


class Momentum(Strategy):
    name = "momentum"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        L = int(self.params.get("lookback", 63))
        mom = df["mid"] / df["mid"].shift(L) - 1.0
        return (mom > 0).astype(float)

    @classmethod
    def param_grid(cls) -> Iterator[dict]:
        for L in (21, 42, 63, 126, 252):
            yield {"lookback": L}


class MovingAverageTrend(Strategy):
    name = "ma_trend"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        f = int(self.params.get("fast", 20))
        s = int(self.params.get("slow", 100))
        fast = df["mid"].rolling(f, min_periods=f).mean()
        slow = df["mid"].rolling(s, min_periods=s).mean()
        return (fast > slow).astype(float)

    @classmethod
    def param_grid(cls) -> Iterator[dict]:
        for f in (10, 20, 50):
            for s in (100, 150, 200):
                if f < s:
                    yield {"fast": f, "slow": s}


class MeanReversionZ(Strategy):
    name = "meanrev_z"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        L = int(self.params.get("lookback", 20))
        k = float(self.params.get("k", 1.0))
        m = df["mid"].rolling(L, min_periods=L).mean()
        sd = df["mid"].rolling(L, min_periods=L).std(ddof=1)
        z = (df["mid"] - m) / sd
        return (z < -k).astype(float)  # compra caídas; largo/plano

    @classmethod
    def param_grid(cls) -> Iterator[dict]:
        for L in (10, 20, 40):
            for k in (0.5, 1.0, 1.5, 2.0):
                yield {"lookback": L, "k": k}


class DonchianBreakout(Strategy):
    name = "breakout"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        L = int(self.params.get("lookback", 55))
        hi = df["mid"].rolling(L, min_periods=L).max().shift(1)
        lo = df["mid"].rolling(L, min_periods=L).min().shift(1)
        raw = pd.Series(np.nan, index=df.index)
        raw[df["mid"] >= hi] = 1.0
        raw[df["mid"] <= lo] = 0.0
        return raw.ffill().fillna(0.0)

    @classmethod
    def param_grid(cls) -> Iterator[dict]:
        for L in (20, 40, 55, 100):
            yield {"lookback": L}


class VolScaledMomentum(Strategy):
    name = "vol_mom"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        L = int(self.params.get("lookback", 63))
        target_vol = float(self.params.get("target_vol", 0.15)) / np.sqrt(252)
        mom = (df["mid"] / df["mid"].shift(L) - 1.0) > 0
        scale = (target_vol / df["sigma_bar"]).clip(upper=1.0)
        return (mom.astype(float) * scale).clip(0.0, 1.0)

    @classmethod
    def param_grid(cls) -> Iterator[dict]:
        for L in (42, 63, 126):
            for tv in (0.10, 0.15, 0.20):
                yield {"lookback": L, "target_vol": tv}


class BuyAndHold(Strategy):
    """Benchmark largo pasivo (referencia a batir)."""

    name = "buy_hold"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)


STRATEGY_CLASSES = [
    Momentum,
    MovingAverageTrend,
    MeanReversionZ,
    DonchianBreakout,
    VolScaledMomentum,
]


def all_candidates() -> list[Strategy]:
    """Todas las configuraciones (para contar pruebas y calcular DSR/PBO)."""
    out: list[Strategy] = []
    for cls in STRATEGY_CLASSES:
        for params in cls.param_grid():
            out.append(cls(**params))
    return out
