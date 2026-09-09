"""Generador de mercado SINTÉTICO — SOLO para demostrar la maquinaria.

⚠️  ADVERTENCIA: estos datos NO son mercado real y NO constituyen evidencia de
ninguna ventaja. Sirven para (a) probar que el arnés de validación corre de
extremo a extremo y (b) verificar que la puerta RECHAZA correctamente cuando no
hay ventaja robusta. Cualquier conclusión de inversión requiere datos reales de
dos fuentes independientes (ver ESTUDIO.md, sección "Evidencia que falta").

Modelo: retorno con régimen por bloques (tendencia / reversión / ruido) sobre una
volatilidad con clustering tipo GARCH(1,1). Se derivan volumen y bid/ask.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SYNTHETIC_WARNING = (
    "DATOS SINTÉTICOS — no son mercado real, no son evidencia de ventaja."
)


@dataclass(frozen=True)
class InstrumentSpec:
    name: str
    asset_class: str
    seed: int
    ann_vol: float = 0.20
    ann_drift: float = 0.05
    regime: str = "mixed"     # trend | meanrev | random | mixed
    adv_value: float = 5.0e8
    base_spread_bps: float = 3.0


def _garch_vol(n: int, ann_vol: float, rng: np.random.Generator) -> np.ndarray:
    """Volatilidad diaria con clustering GARCH(1,1)."""
    daily = ann_vol / np.sqrt(252)
    omega, alpha, beta = 0.05, 0.08, 0.87  # persistencia realista
    var0 = daily**2
    long_run = omega * var0 / max(1e-9, (1 - alpha - beta))
    var = np.empty(n)
    var[0] = var0
    eps = rng.standard_normal(n)
    for t in range(1, n):
        var[t] = long_run * (1 - alpha - beta) + alpha * (eps[t - 1] ** 2) * var[t - 1] + beta * var[t - 1]
    return np.sqrt(var)


def _regime_returns(n: int, sigma: np.ndarray, drift: float, regime: str, rng: np.random.Generator) -> np.ndarray:
    """Retornos con estructura por régimen (débil y realista)."""
    daily_drift = drift / 252
    z = rng.standard_normal(n)
    base = daily_drift + sigma * z
    if regime == "random":
        return base
    r = base.copy()
    if regime in ("trend", "mixed"):
        # momentum débil: pequeña autocorrelación positiva por bloques
        phi = 0.05
        for t in range(1, n):
            r[t] += phi * r[t - 1]
    if regime in ("meanrev", "mixed"):
        # reversión débil superpuesta en otros bloques
        block = 63
        for start in range(0, n, block * 2):
            end = min(n, start + block)
            seg = r[start:end]
            r[start:end] = seg - 0.10 * (np.cumsum(seg) - seg)  # tira hacia la media
    return r


def generate_instrument(spec: InstrumentSpec, n_days: int, start: str = "2015-01-02") -> pd.DataFrame:
    rng = np.random.default_rng(spec.seed)
    dates = pd.bdate_range(start=start, periods=n_days)
    sigma = _garch_vol(n_days, spec.ann_vol, rng)
    ret = _regime_returns(n_days, sigma, spec.ann_drift, spec.regime, rng)
    mid = 100.0 * np.cumprod(1.0 + ret)
    # Volumen: lognormal centrado en ADV, anticorrelado débilmente con precio.
    vol_noise = rng.lognormal(mean=0.0, sigma=0.4, size=n_days)
    volume_value = spec.adv_value * vol_noise
    # Diferencial: base + prima por volatilidad.
    spread_bps = spec.base_spread_bps + 50.0 * sigma
    half = mid * (spread_bps / 1e4) / 2.0
    df = pd.DataFrame(
        {
            "mid": mid,
            "bid": mid - half,
            "ask": mid + half,
            "volume_value": volume_value,
            "sigma_bar": sigma,
            "spread_bps": spread_bps,
        },
        index=dates,
    )
    df.attrs["synthetic_warning"] = SYNTHETIC_WARNING
    df.attrs["asset_class"] = spec.asset_class
    return df


def default_universe(n_days: int = 1500) -> dict[str, pd.DataFrame]:
    """Universo sintético multi-activo (acciones, ETF, FX, materia prima, cripto)."""
    specs = [
        InstrumentSpec("EQ_A", "equity", 101, ann_vol=0.22, ann_drift=0.07, regime="trend", adv_value=8e8),
        InstrumentSpec("EQ_B", "equity", 102, ann_vol=0.28, ann_drift=0.04, regime="meanrev", adv_value=4e8),
        InstrumentSpec("ETF_W", "etf", 103, ann_vol=0.15, ann_drift=0.05, regime="mixed", adv_value=2e9),
        InstrumentSpec("FX_EURUSD", "fx", 104, ann_vol=0.08, ann_drift=0.00, regime="meanrev", adv_value=5e10, base_spread_bps=0.5),
        InstrumentSpec("CO_GOLD", "commodity", 105, ann_vol=0.16, ann_drift=0.03, regime="mixed", adv_value=1e10),
        InstrumentSpec("CR_BTC", "crypto", 106, ann_vol=0.65, ann_drift=0.10, regime="trend", adv_value=2e9, base_spread_bps=6.0),
    ]
    return {s.name: generate_instrument(s, n_days) for s in specs}
