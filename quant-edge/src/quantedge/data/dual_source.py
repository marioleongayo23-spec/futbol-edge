"""Reconciliación de dos fuentes de datos independientes.

El encargo exige comparar >= 2 fuentes. Aquí se implementa la lógica de
reconciliación (detección de discrepancias, limpieza, informe de calidad). Con
datos sintéticos se simulan dos "vendors" añadiendo ruido de medición y ticks
erróneos ocasionales; con datos reales se sustituyen por los adaptadores de dos
proveedores distintos (ver loader.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def make_vendor_copy(df: pd.DataFrame, seed: int, bad_tick_prob: float = 0.002) -> pd.DataFrame:
    """Simula una fuente: mid con ruido de medición y algún tick erróneo."""
    rng = np.random.default_rng(seed)
    out = df.copy()
    noise = 1.0 + rng.normal(0, 2e-4, size=len(df))  # ~2 bps de ruido
    out["mid"] = out["mid"] * noise
    bad = rng.random(len(df)) < bad_tick_prob
    out.loc[bad, "mid"] = out.loc[bad, "mid"] * rng.choice([0.9, 1.1], size=bad.sum())
    half = out["mid"] * (out["spread_bps"] / 1e4) / 2.0
    out["bid"] = out["mid"] - half
    out["ask"] = out["mid"] + half
    return out


@dataclass
class ReconcileReport:
    n_bars: int
    max_abs_bp_diff: float
    frac_bars_flagged: float       # fracción de barras con desacuerdo > umbral
    flagged_threshold_bps: float


def reconcile(a: pd.DataFrame, b: pd.DataFrame, threshold_bps: float = 20.0) -> tuple[pd.DataFrame, ReconcileReport]:
    """Reconcilia dos fuentes por la mediana robusta; marca discrepancias.

    Regla de limpieza: si |a-b|/mid > umbral, se marca y se usa la fuente más
    próxima a la mediana móvil (proxy de consenso). Devuelve el df limpio y un
    informe de calidad que la puerta puede exigir (fuentes coherentes).
    """
    idx = a.index.intersection(b.index)
    a, b = a.loc[idx], b.loc[idx]
    mid_a, mid_b = a["mid"].to_numpy(), b["mid"].to_numpy()
    ref = (mid_a + mid_b) / 2.0
    bp_diff = np.abs(mid_a - mid_b) / ref * 1e4
    flagged = bp_diff > threshold_bps
    # Consenso: mediana móvil robusta como árbitro para las barras marcadas.
    consensus = pd.Series(ref, index=idx).rolling(5, min_periods=1, center=True).median().to_numpy()
    chosen = np.where(
        np.abs(mid_a - consensus) <= np.abs(mid_b - consensus), mid_a, mid_b
    )
    clean_mid = np.where(flagged, consensus, chosen)
    clean = a.copy()
    clean["mid"] = clean_mid
    half = clean["mid"] * (clean["spread_bps"] / 1e4) / 2.0
    clean["bid"] = clean["mid"] - half
    clean["ask"] = clean["mid"] + half
    report = ReconcileReport(
        n_bars=len(idx),
        max_abs_bp_diff=float(np.nanmax(bp_diff)) if len(idx) else float("nan"),
        frac_bars_flagged=float(np.mean(flagged)) if len(idx) else float("nan"),
        flagged_threshold_bps=threshold_bps,
    )
    return clean, report
