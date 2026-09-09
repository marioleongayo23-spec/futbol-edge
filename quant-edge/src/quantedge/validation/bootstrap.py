"""Bootstrap para series dependientes + Monte Carlo de trayectorias.

El bootstrap i.i.d. es inválido para retornos financieros (autocorrelación,
clustering de volatilidad). Usamos:
  - Bootstrap estacionario (Politis & Romano, 1994): bloques de longitud
    geométrica aleatoria.
  - Bootstrap circular por bloques (longitud fija).
Ambos preservan la dependencia de corto plazo. Con ellos calculamos intervalos
de confianza de las métricas y, por Monte Carlo, la distribución de resultados
futuros (drawdown, probabilidad de alcanzar el objetivo, probabilidad de pérdida).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .metrics import geometric_mean, max_drawdown_from_array


def stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Índices de un remuestreo por bootstrap estacionario de longitud n."""
    if mean_block < 1:
        mean_block = 1.0
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=np.int64)
    cur = rng.integers(0, n)
    for i in range(n):
        idx[i] = cur
        if rng.random() < p:
            cur = rng.integers(0, n)  # nuevo bloque
        else:
            cur = (cur + 1) % n  # continúa el bloque (circular)
    return idx


def circular_block_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    block = max(1, int(block))
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    idx = np.concatenate([(np.arange(s, s + block) % n) for s in starts])[:n]
    return idx.astype(np.int64)


@dataclass
class BootstrapCI:
    point: float
    lo: float
    hi: float
    alpha: float
    n_boot: int


def bootstrap_ci(
    returns: np.ndarray,
    stat_fn,
    n_boot: int = 2000,
    mean_block: float = 10.0,
    alpha: float = 0.05,
    seed: int = 12345,
) -> BootstrapCI:
    """Intervalo de confianza percentil para un estadístico bajo bootstrap estacionario."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = stationary_bootstrap_indices(n, mean_block, rng)
        stats[b] = stat_fn(r[idx])
    lo = float(np.quantile(stats, alpha / 2))
    hi = float(np.quantile(stats, 1 - alpha / 2))
    return BootstrapCI(point=float(stat_fn(r)), lo=lo, hi=hi, alpha=alpha, n_boot=n_boot)


@dataclass
class MonteCarloResult:
    horizon: int
    n_paths: int
    target_daily: float
    prob_hit_target: float          # P(media diaria geométrica del tramo >= objetivo)
    prob_positive: float            # P(retorno acumulado > 0)
    median_geo_daily: float
    p05_geo_daily: float
    p95_geo_daily: float
    median_max_drawdown: float
    p95_max_drawdown: float         # cola mala del drawdown

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def monte_carlo(
    returns: np.ndarray,
    horizon: int | None = None,
    n_paths: int = 5000,
    mean_block: float = 10.0,
    target_daily: float = 0.004,
    seed: int = 7,
) -> MonteCarloResult:
    """Distribución de trayectorias futuras remuestreando bloques de los retornos.

    NO inventa retornos: solo recombina los observados preservando dependencia.
    Da una lectura *probabilística* del objetivo, no una promesa.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if horizon is None:
        horizon = n
    rng = np.random.default_rng(seed)
    geo = np.empty(n_paths)
    mdd = np.empty(n_paths)
    pos = np.empty(n_paths)
    for p in range(n_paths):
        idx = stationary_bootstrap_indices(n, mean_block, rng)[:horizon]
        path = r[idx]
        geo[p] = geometric_mean(path)
        mdd[p] = max_drawdown_from_array(path)
        pos[p] = 1.0 if np.prod(1.0 + path) > 1.0 else 0.0
    return MonteCarloResult(
        horizon=horizon,
        n_paths=n_paths,
        target_daily=target_daily,
        prob_hit_target=float(np.mean(geo >= target_daily)),
        prob_positive=float(np.mean(pos)),
        median_geo_daily=float(np.median(geo)),
        p05_geo_daily=float(np.quantile(geo, 0.05)),
        p95_geo_daily=float(np.quantile(geo, 0.95)),
        median_max_drawdown=float(np.median(mdd)),
        p95_max_drawdown=float(np.quantile(mdd, 0.95)),
    )
