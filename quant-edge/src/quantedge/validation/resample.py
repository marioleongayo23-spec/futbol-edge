"""Puente intradía -> diario.

El objetivo se mide sobre retornos DIARIOS, pero los datos pueden ser intradía.
Estas utilidades componen los retornos intradía dentro de cada sesión para
obtener el retorno diario, que es lo que consume `metrics.monthly_geometric_
daily_mean`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def intraday_returns_to_daily(returns: pd.Series) -> pd.Series:
    """Compone retornos intradía a retorno diario por sesión (día natural)."""
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("Se requiere DatetimeIndex")
    daily = returns.groupby(returns.index.normalize()).apply(
        lambda s: float(np.prod(1.0 + s.to_numpy())) - 1.0
    )
    daily.index = pd.DatetimeIndex(daily.index)
    return daily


def bars_frequency(index: pd.DatetimeIndex) -> str:
    """Heurística: 'intraday' si hay >1 barra por día, si no 'daily'."""
    if len(index) < 2:
        return "daily"
    per_day = index.normalize().value_counts()
    return "intraday" if per_day.max() > 1 else "daily"
