"""Challenger residual 1X2 con validación temporal y activación protegida."""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize

from .ensemble import GATE_METRICS, _paired, candidate_beats_all_baselines, temporal_split_index
from .metrics import aggregate

SIGNS = ("1", "X", "2")
MIN_RECORDS = 80


def _normalise(probs: dict[str, float]) -> np.ndarray:
    values = np.array([max(1e-8, float(probs.get(sign, 0))) for sign in SIGNS], dtype=float)
    return values / values.sum()


def _features(dc: dict[str, float], elo: dict[str, float]) -> np.ndarray:
    dixon, rating = _normalise(dc), _normalise(elo)
    entropy = -float(np.sum(dixon * np.log(dixon))) / math.log(3)
    return np.array([
        dixon[0] - rating[0], dixon[1] - rating[1], dixon[2] - rating[2],
        dixon[0] - dixon[2], entropy,
    ])


def _prepare(rows, mean=None, scale=None):
    raw = np.vstack([_features(dc, elo) for dc, elo, _actual in rows])
    if mean is None:
        mean = raw.mean(axis=0)
    if scale is None:
        scale = raw.std(axis=0)
    scale = np.where(scale < 1e-6, 1.0, scale)
    return (raw - mean) / scale, mean, scale


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def _fit(rows, l2: float = 0.12) -> dict:
    x, mean, scale = _prepare(rows)
    x = np.column_stack([np.ones(len(x)), x])
    base = np.vstack([np.log(_normalise(dc)) for dc, _elo, _actual in rows])
    y = np.array([SIGNS.index(actual) for _dc, _elo, actual in rows])

    def objective(flat):
        weights = flat.reshape(3, x.shape[1])
        probabilities = _softmax(base + x @ weights.T)
        loss = -np.log(np.maximum(1e-12, probabilities[np.arange(len(y)), y])).mean()
        return float(loss + l2 * np.mean(weights[:, 1:] ** 2))

    result = minimize(objective, np.zeros(3 * x.shape[1]), method="L-BFGS-B")
    weights = result.x.reshape(3, x.shape[1]) if result.success else np.zeros((3, x.shape[1]))
    return {
        "weights": weights.round(8).tolist(),
        "feature_mean": mean.round(8).tolist(),
        "feature_scale": scale.round(8).tolist(),
        "l2": l2,
        "converged": bool(result.success),
    }


def residual_probabilities(dc: dict[str, float], elo: dict[str, float], params: dict) -> dict[str, float]:
    """Aplica parámetros validados; ante metadatos rotos cae de forma segura a DC."""
    try:
        weights = np.asarray(params["weights"], dtype=float)
        mean = np.asarray(params["feature_mean"], dtype=float)
        scale = np.asarray(params["feature_scale"], dtype=float)
        z = (_features(dc, elo) - mean) / np.where(scale < 1e-6, 1.0, scale)
        probs = _softmax(np.log(_normalise(dc)) + weights @ np.concatenate(([1.0], z)))
        if not np.all(np.isfinite(probs)):
            raise ValueError("non-finite residual output")
        return {sign: float(probs[index]) for index, sign in enumerate(SIGNS)}
    except (KeyError, TypeError, ValueError):
        raw = _normalise(dc)
        return {sign: float(raw[index]) for index, sign in enumerate(SIGNS)}


def fit_walk_forward_residual(
    dc_records: list[dict], elo_records: list[dict], validation_fraction: float = 0.30,
) -> dict:
    """Entrena en el pasado y deja una cola temporal totalmente fuera de muestra."""
    rows = _paired(dc_records, elo_records)
    if len(rows) < MIN_RECORDS:
        return {
            "method": "residual-logit-temporal", "accepted": False,
            "status": "blocked_insufficient_sample", "n": len(rows),
            "minimum_required": MIN_RECORDS,
        }
    split = max(55, min(len(rows) - 20, round(len(rows) * (1 - validation_fraction))))
    split = temporal_split_index(dc_records, elo_records, split, 55, 20)
    if split is None:
        return {"method": "residual-logit-temporal", "accepted": False,
                "status": "blocked_no_temporal_boundary", "n": len(rows)}
    train, validation = rows[:split], rows[split:]
    fitted = _fit(train)
    metrics = aggregate([
        (residual_probabilities(dc, elo, fitted), actual)
        for dc, elo, actual in validation
    ])
    baselines = {
        "dixon_coles": aggregate([(dc, actual) for dc, _elo, actual in validation]),
        "elo": aggregate([(elo, actual) for _dc, elo, actual in validation]),
    }
    accepted = fitted["converged"] and candidate_beats_all_baselines(metrics, baselines)
    return {
        "method": "residual-logit-temporal",
        "accepted": bool(accepted),
        "status": "accepted" if accepted else "blocked_by_gate",
        "n_train": len(train), "n_validation": len(validation),
        "validation": metrics, "validation_baselines": baselines,
        "acceptance_gate": {
            "rule": "strictly_better_than_dixon_coles_and_elo",
            "metrics": list(GATE_METRICS),
        },
        "production": _fit(rows),
    }
