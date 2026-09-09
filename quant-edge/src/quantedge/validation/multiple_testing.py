"""Corrección por pruebas múltiples y sobreajuste.

Probar muchas estrategias/parámetros infla el mejor resultado. Aquí:
  - PBO (Probability of Backtest Overfitting) por CSCV (Bailey, Borwein,
    López de Prado & Zhu, 2017): probabilidad de que la config mejor en muestra
    quede por debajo de la mediana fuera de muestra.
  - Bonferroni y Benjamini-Hochberg (FDR) para p-valores de múltiples estrategias.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
from scipy.stats import rankdata


def _sharpe_cols(mat: np.ndarray) -> np.ndarray:
    """Sharpe por observación de cada columna (estrategia)."""
    mu = mat.mean(axis=0)
    sd = mat.std(axis=0, ddof=1)
    sd = np.where(sd == 0, np.nan, sd)
    return mu / sd


def pbo_cscv(perf_matrix: np.ndarray, n_groups: int = 10) -> dict:
    """PBO por CSCV. perf_matrix: (T observaciones x N estrategias) de retornos.

    Devuelve la probabilidad de sobreajuste y la distribución de logits.
    """
    R = np.asarray(perf_matrix, dtype=float)
    T, N = R.shape
    if N < 2:
        raise ValueError("Se necesitan >= 2 estrategias para PBO")
    if n_groups % 2 != 0:
        n_groups -= 1
    groups = [g for g in np.array_split(np.arange(T), n_groups) if g.size]
    S = len(groups)
    logits: list[float] = []
    below_median = 0
    combos = list(combinations(range(S), S // 2))
    for train_g in combos:
        train_rows = np.concatenate([groups[i] for i in train_g])
        test_g = [i for i in range(S) if i not in train_g]
        test_rows = np.concatenate([groups[i] for i in test_g])
        is_perf = _sharpe_cols(R[train_rows])
        oos_perf = _sharpe_cols(R[test_rows])
        n_star = int(np.nanargmax(is_perf))
        ranks = rankdata(oos_perf)  # 1..N ascendente (mayor = mejor)
        rank = ranks[n_star]
        omega = rank / (N + 1)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        lam = float(np.log(omega / (1 - omega)))
        logits.append(lam)
        if lam <= 0:
            below_median += 1
    return {
        "pbo": below_median / len(combos),
        "n_combinations": len(combos),
        "logit_mean": float(np.mean(logits)),
        "logit_median": float(np.median(logits)),
    }


def bonferroni(pvalues: np.ndarray) -> np.ndarray:
    p = np.asarray(pvalues, dtype=float)
    return np.clip(p * p.size, 0.0, 1.0)


def benjamini_hochberg(pvalues: np.ndarray, alpha: float = 0.05) -> dict:
    """FDR de Benjamini-Hochberg. Devuelve máscara de rechazos y q-valores."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * m / (np.arange(1, m + 1))
    # q-valores monótonos (de mayor a menor)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    qvals = np.empty(m)
    qvals[order] = q
    rejected = qvals <= alpha
    return {"rejected": rejected, "qvalues": qvals, "n_rejected": int(rejected.sum())}
