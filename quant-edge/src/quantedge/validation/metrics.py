"""Métricas de rendimiento y riesgo, todas sobre retornos NETOS (tras costes).

La métrica objetivo del encargo es la **media diaria geométrica mensual**:
para cada mes natural, la media geométrica de los retornos diarios de ese mes.
El objetivo es >= 0,4% (aspirando a 0,6%).

Incluye Sharpe Probabilístico (PSR, Bailey & López de Prado 2012) y Sharpe
Desinflado (DSR, Bailey & López de Prado 2014), que corrigen el Sharpe por
longitud de muestra, no-normalidad y número de pruebas realizadas.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

EULER_MASCHERONI = 0.5772156649015329


def equity_curve(returns: pd.Series) -> pd.Series:
    """Curva de capital multiplicativa a partir de retornos simples diarios."""
    return (1.0 + returns.fillna(0.0)).cumprod()


def geometric_mean(returns: np.ndarray | pd.Series) -> float:
    """Media geométrica de retornos simples: exp(mean(log(1+r)))-1."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return float("nan")
    return float(np.expm1(np.mean(np.log1p(r))))


def monthly_geometric_daily_mean(returns: pd.Series) -> pd.Series:
    """Serie con la media diaria geométrica de cada mes natural.

    Índice = Period mensual; valor = geometric_mean de los retornos diarios de
    ese mes. Es la magnitud que la puerta de aplicación compara con 0,4%/0,6%.
    """
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("returns debe tener DatetimeIndex para agrupar por mes")
    grouped = returns.groupby(returns.index.to_period("M"))
    return grouped.apply(lambda s: geometric_mean(s.to_numpy()))


def max_drawdown_from_array(returns: np.ndarray) -> float:
    """Drawdown máximo (positivo) sobre un array de retornos simples."""
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return float("nan")
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(-dd.min())


def max_drawdown(returns: pd.Series) -> float:
    """Drawdown máximo (positivo, p.ej. 0.20 = -20%)."""
    return max_drawdown_from_array(returns.fillna(0.0).to_numpy())


def sharpe_per_observation(returns: np.ndarray | pd.Series, rf: float = 0.0) -> float:
    """Sharpe por observación (sin anualizar): mean/std con ddof=1."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float((r.mean() - rf) / sd)


def annualized_sharpe(returns: pd.Series, periods_per_year: int = 252, rf: float = 0.0) -> float:
    return sharpe_per_observation(returns, rf=rf) * np.sqrt(periods_per_year)


def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    g = geometric_mean(returns)
    return float((1.0 + g) ** periods_per_year - 1.0)


def probabilistic_sharpe_ratio(
    returns: np.ndarray | pd.Series, sr_benchmark: float = 0.0
) -> float:
    """P(Sharpe verdadero > sr_benchmark), por observación.

    Usa el error estándar de Lo (2002) corregido por asimetría y curtosis
    (fórmula PSR de Bailey & López de Prado). `sr_benchmark` en unidades de
    Sharpe por observación.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 3:
        return float("nan")
    sr = sharpe_per_observation(r)
    g3 = float(skew(r, bias=False))
    g4 = float(kurtosis(r, fisher=False, bias=False))  # curtosis NO en exceso
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr**2
    if denom <= 0:
        return float("nan")
    z = (sr - sr_benchmark) * np.sqrt(n - 1) / np.sqrt(denom)
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Sharpe máximo esperado por puro azar tras `n_trials` pruebas.

    sr_variance = varianza (entre pruebas) de las estimaciones de Sharpe por
    observación. Aproximación de valores extremos usada en el DSR.
    """
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(sr_variance) * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2))


def deflated_sharpe_ratio(
    returns: np.ndarray | pd.Series, n_trials: int, sr_variance: float
) -> float:
    """Sharpe Desinflado: PSR frente al Sharpe máximo esperado por azar.

    Un DSR alto (p.ej. > 0,95) indica que el Sharpe observado difícilmente se
    explica por haber probado muchas configuraciones. Es la corrección clave
    contra el sesgo de selección / pruebas múltiples.
    """
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    return probabilistic_sharpe_ratio(returns, sr_benchmark=sr0)


@dataclass
class PerformanceSummary:
    n_days: int
    n_months: int
    geo_daily_mean: float
    monthly_geo_daily_mean_mean: float
    monthly_geo_daily_mean_median: float
    monthly_geo_daily_mean_min: float
    months_hitting_target: float  # fracción de meses con media diaria >= objetivo
    ann_return: float
    ann_sharpe: float
    max_drawdown: float
    psr: float
    monthly_series: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["monthly_series"] = {str(k): float(v) for k, v in self.monthly_series.items()}
        return d


def summarize(
    returns: pd.Series, target_daily: float = 0.004, periods_per_year: int = 252
) -> PerformanceSummary:
    monthly = monthly_geometric_daily_mean(returns)
    hit = float((monthly >= target_daily).mean()) if len(monthly) else float("nan")
    return PerformanceSummary(
        n_days=int(returns.notna().sum()),
        n_months=int(len(monthly)),
        geo_daily_mean=geometric_mean(returns),
        monthly_geo_daily_mean_mean=float(monthly.mean()) if len(monthly) else float("nan"),
        monthly_geo_daily_mean_median=float(monthly.median()) if len(monthly) else float("nan"),
        monthly_geo_daily_mean_min=float(monthly.min()) if len(monthly) else float("nan"),
        months_hitting_target=hit,
        ann_return=annualized_return(returns, periods_per_year),
        ann_sharpe=annualized_sharpe(returns, periods_per_year),
        max_drawdown=max_drawdown(returns),
        psr=probabilistic_sharpe_ratio(returns, 0.0),
        monthly_series={str(k): float(v) for k, v in monthly.items()},
    )
