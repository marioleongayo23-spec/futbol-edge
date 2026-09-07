"""Challenger 1X2 con xG/npxG/PSxG avanzado y gate temporal estricto.

P2.3 es deliberadamente *offline/report-only*: aprende una corrección sobre el
motor base usando únicamente snapshots avanzados disponibles ANTES del kickoff.
Aunque supere el gate, este módulo no tiene ningún camino de escritura hacia
``probs`` de producción. La promoción requiere un cambio posterior explícito.

La comparación se hace sobre exactamente la misma muestra y cola temporal contra:
- motor base (híbrido DC+pseudo-xG o DC),
- Elo,
- residual estándar actual reentrenado en la misma muestra,
- cualquier baseline extra con cobertura completa (p. ej. DC si el base es híbrido,
  o mercado no-vig cuando exista un histórico alineado).
"""

from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np
from scipy.optimize import minimize

from ..advanced_stats import latest_snapshot_as_of, match_context
from .ensemble import (
    GATE_METRICS,
    _paired_records,
    _record_key,
    candidate_beats_all_baselines,
    grouped_split_index,
)
from .metrics import aggregate
from .residual import _fit as _fit_standard_residual
from .residual import residual_probabilities

SIGNS = ("1", "X", "2")
SCHEMA = "advanced-outcome-residual-v1"
METHOD = "advanced-residual-logit-temporal-v1"
MIN_RECORDS = 100
MIN_TRAIN = 70
MIN_VALIDATION = 25

FEATURES = [
    "base_minus_elo_1",
    "base_minus_elo_x",
    "base_minus_elo_2",
    "base_home_away_gap",
    "base_entropy",
    "xg_home_attack_edge",
    "xg_away_attack_edge",
    "xg_net_edge",
    "npxg_net_edge",
    "npxg_available_both",
    "keeper_psxg_plusminus_delta",
    "keeper_available_both",
    "home_sample_log",
    "away_sample_log",
]


def _normalise(probs: dict[str, float]) -> np.ndarray:
    values = np.array(
        [max(1e-8, float(probs.get(sign, 0.0))) for sign in SIGNS], dtype=float
    )
    total = float(values.sum())
    return values / (total if total > 0 else 1.0)


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _base_features(base: dict[str, float], elo: dict[str, float]) -> list[float]:
    b, e = _normalise(base), _normalise(elo)
    entropy = -float(np.sum(b * np.log(b))) / math.log(3)
    return [
        float(b[0] - e[0]),
        float(b[1] - e[1]),
        float(b[2] - e[2]),
        float(b[0] - b[2]),
        entropy,
    ]


def _advanced_values(context: dict) -> list[float] | None:
    """Extrae señales avanzadas; xG for/against de ambos lados es obligatorio."""
    if not isinstance(context, dict):
        return None
    home, away = context.get("home") or {}, context.get("away") or {}
    required = (
        home.get("xg_for90"),
        home.get("xg_against90"),
        away.get("xg_for90"),
        away.get("xg_against90"),
    )
    if any(value is None for value in required):
        return None
    h_for, h_against, a_for, a_against = map(_finite, required)
    home_attack_edge = h_for - a_against
    away_attack_edge = a_for - h_against
    xg_net = home_attack_edge - away_attack_edge

    h_npf = home.get("npxg_for90")
    h_npa = home.get("npxg_against90")
    a_npf = away.get("npxg_for90")
    a_npa = away.get("npxg_against90")
    npxg_both = all(value is not None for value in (h_npf, h_npa, a_npf, a_npa))
    if npxg_both:
        npxg_net = (_finite(h_npf) - _finite(a_npa)) - (
            _finite(a_npf) - _finite(h_npa)
        )
    else:
        # Neutraliza el valor pero conserva un indicador explícito de ausencia.
        npxg_net = 0.0

    h_keeper = (home.get("goalkeeper") or {}).get("psxg_plus_minus90_shrunk")
    a_keeper = (away.get("goalkeeper") or {}).get("psxg_plus_minus90_shrunk")
    keeper_both = h_keeper is not None and a_keeper is not None
    keeper_delta = _finite(h_keeper) - _finite(a_keeper) if keeper_both else 0.0

    return [
        home_attack_edge,
        away_attack_edge,
        xg_net,
        npxg_net,
        1.0 if npxg_both else 0.0,
        keeper_delta,
        1.0 if keeper_both else 0.0,
        math.log1p(max(0, int(_finite(home.get("matches"))))),
        math.log1p(max(0, int(_finite(away.get("matches"))))),
    ]


def _features(base: dict[str, float], elo: dict[str, float], context: dict) -> np.ndarray | None:
    advanced = _advanced_values(context)
    if advanced is None:
        return None
    return np.asarray(_base_features(base, elo) + advanced, dtype=float)


def _prepare(rows, mean=None, scale=None):
    raw = np.vstack([_features(base, elo, context) for base, elo, context, _actual, _record in rows])
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


def _fit(rows, l2: float = 0.18) -> dict:
    x, mean, scale = _prepare(rows)
    x = np.column_stack([np.ones(len(x)), x])
    base = np.vstack([np.log(_normalise(row[0])) for row in rows])
    y = np.asarray([SIGNS.index(row[3]) for row in rows], dtype=int)

    def objective(flat):
        weights = flat.reshape(3, x.shape[1])
        probabilities = _softmax(base + x @ weights.T)
        loss = -np.log(
            np.maximum(1e-12, probabilities[np.arange(len(y)), y])
        ).mean()
        # Regularización algo mayor que el residual estándar: hay más features y
        # el histórico avanzado será inicialmente pequeño.
        return float(loss + l2 * np.mean(weights[:, 1:] ** 2))

    result = minimize(
        objective,
        np.zeros(3 * x.shape[1]),
        method="L-BFGS-B",
    )
    weights = (
        result.x.reshape(3, x.shape[1])
        if result.success
        else np.zeros((3, x.shape[1]))
    )
    return {
        "schema": SCHEMA,
        "features": list(FEATURES),
        "weights": weights.round(8).tolist(),
        "feature_mean": mean.round(8).tolist(),
        "feature_scale": scale.round(8).tolist(),
        "l2": l2,
        "converged": bool(result.success),
    }


def advanced_residual_probabilities(
    base: dict[str, float],
    elo: dict[str, float],
    context: dict,
    params: dict,
) -> dict[str, float]:
    """Aplica el challenger; cualquier metadato inválido cae al motor base."""
    try:
        weights = np.asarray(params["weights"], dtype=float)
        mean = np.asarray(params["feature_mean"], dtype=float)
        scale = np.asarray(params["feature_scale"], dtype=float)
        feature = _features(base, elo, context)
        if feature is None:
            raise ValueError("advanced features unavailable")
        z = (feature - mean) / np.where(scale < 1e-6, 1.0, scale)
        probabilities = _softmax(
            np.log(_normalise(base)) + weights @ np.concatenate(([1.0], z))
        )
        if not np.all(np.isfinite(probabilities)):
            raise ValueError("non-finite advanced residual output")
        return {
            sign: float(probabilities[index])
            for index, sign in enumerate(SIGNS)
        }
    except (KeyError, TypeError, ValueError, IndexError):
        raw = _normalise(base)
        return {sign: float(raw[index]) for index, sign in enumerate(SIGNS)}


def _cutoff(record: dict) -> datetime | None:
    stamp = record.get("kickoff")
    if isinstance(stamp, (int, float)) and math.isfinite(float(stamp)):
        return datetime.fromtimestamp(float(stamp), tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _advanced_rows(
    base_records: list[dict],
    elo_records: list[dict],
    archive: dict | list,
    *,
    league: str,
    season: int,
) -> tuple[list[tuple], dict]:
    paired = _paired_records(base_records, elo_records)
    rows = []
    snapshot_n = 0
    context_n = 0
    xg_complete_n = 0
    for base_record, elo_record in paired:
        cutoff = _cutoff(base_record)
        if cutoff is None:
            continue
        snapshot = latest_snapshot_as_of(archive, league, season, cutoff)
        if snapshot is None:
            continue
        snapshot_n += 1
        context = match_context(
            snapshot,
            str(base_record.get("home") or ""),
            str(base_record.get("away") or ""),
        )
        if context is None:
            continue
        context_n += 1
        if _advanced_values(context) is None:
            continue
        xg_complete_n += 1
        rows.append(
            (
                base_record["probs"],
                elo_record["probs"],
                context,
                base_record["actual"],
                base_record,
            )
        )
    return rows, {
        "paired_predictions": len(paired),
        "snapshot_available": snapshot_n,
        "match_context_available": context_n,
        "xg_complete": xg_complete_n,
        "usable": len(rows),
        "pct_of_paired": round(100.0 * len(rows) / len(paired), 1) if paired else 0.0,
        "cutoff_rule": "advanced_snapshot.available_at < match.kickoff",
    }


def _validation_extra_baselines(
    validation_rows: list[tuple],
    records_by_name: dict[str, list[dict]] | None,
) -> tuple[dict[str, dict], dict[str, dict], bool]:
    metrics: dict[str, dict] = {}
    coverage: dict[str, dict] = {}
    complete_all = True
    for name, records in (records_by_name or {}).items():
        by_key = {_record_key(record): record for record in records}
        samples = []
        for _base, _elo, _context, actual, base_record in validation_rows:
            other = by_key.get(_record_key(base_record))
            if other and other.get("probs"):
                samples.append((other["probs"], actual))
        complete = len(samples) == len(validation_rows) and bool(samples)
        coverage[name] = {
            "n": len(samples),
            "required": len(validation_rows),
            "complete": complete,
        }
        if complete:
            metrics[name] = aggregate(samples)
        else:
            complete_all = False
    return metrics, coverage, complete_all


def fit_walk_forward_advanced_residual(
    base_records: list[dict],
    elo_records: list[dict],
    archive: dict | list,
    *,
    league: str,
    season: int,
    base_name: str = "hybrid_dixon_coles",
    extra_baseline_records: dict[str, list[dict]] | None = None,
    validation_fraction: float = 0.30,
) -> dict:
    """Entrena y valida P2.3 sobre una muestra temporal leakage-safe.

    El resultado puede decir ``accepted`` en sentido estadístico, pero conserva
    siempre ``affects_1x2=False`` y ``promotion_status=manual_future_pr_required``.
    """
    rows, coverage = _advanced_rows(
        base_records,
        elo_records,
        archive,
        league=league,
        season=season,
    )
    if len(rows) < MIN_RECORDS:
        return {
            "method": METHOD,
            "schema": SCHEMA,
            "accepted": False,
            "status": "blocked_insufficient_advanced_snapshots",
            "n": len(rows),
            "minimum_required": MIN_RECORDS,
            "coverage": coverage,
            "affects_1x2": False,
            "promotion_status": "manual_future_pr_required",
        }

    blocks = []
    for row in rows:
        stamp = row[4].get("kickoff")
        if isinstance(stamp, (int, float)):
            blocks.append(("day", int(float(stamp) // 86400)))
        else:
            blocks.append(("round", tuple(row[4].get("round") or ())))
    desired = max(
        MIN_TRAIN,
        min(len(rows) - MIN_VALIDATION, round(len(rows) * (1 - validation_fraction))),
    )
    split = grouped_split_index(blocks, desired, MIN_TRAIN, MIN_VALIDATION)
    if split is None:
        return {
            "method": METHOD,
            "schema": SCHEMA,
            "accepted": False,
            "status": "blocked_no_temporal_boundary",
            "n": len(rows),
            "coverage": coverage,
            "affects_1x2": False,
            "promotion_status": "manual_future_pr_required",
        }

    train, validation = rows[:split], rows[split:]
    fitted = _fit(train)
    candidate_metrics = aggregate(
        [
            (
                advanced_residual_probabilities(base, elo, context, fitted),
                actual,
            )
            for base, elo, context, actual, _record in validation
        ]
    )

    # Baselines exactos sobre la misma cola.
    base_metrics = aggregate([(base, actual) for base, _elo, _ctx, actual, _r in validation])
    elo_metrics = aggregate([(elo, actual) for _base, elo, _ctx, actual, _r in validation])

    standard_train = [(base, elo, actual) for base, elo, _ctx, actual, _r in train]
    standard_params = _fit_standard_residual(standard_train)
    standard_metrics = aggregate(
        [
            (residual_probabilities(base, elo, standard_params), actual)
            for base, elo, _ctx, actual, _r in validation
        ]
    )

    baselines = {
        base_name: base_metrics,
        "elo": elo_metrics,
        "residual_same_sample": standard_metrics,
    }
    extra_metrics, extra_coverage, complete_extras = _validation_extra_baselines(
        validation,
        extra_baseline_records,
    )
    baselines.update(extra_metrics)

    accepted = (
        fitted.get("converged") is True
        and standard_params.get("converged") is True
        and complete_extras
        and candidate_beats_all_baselines(candidate_metrics, baselines)
    )
    if not complete_extras:
        status = "blocked_incomplete_baseline_coverage"
    elif accepted:
        status = "accepted_offline_not_promoted"
    else:
        status = "blocked_by_gate"

    return {
        "method": METHOD,
        "schema": SCHEMA,
        "accepted": bool(accepted),
        "status": status,
        "n": len(rows),
        "n_train": len(train),
        "n_validation": len(validation),
        "coverage": coverage,
        "validation": candidate_metrics,
        "validation_baselines": baselines,
        "baseline_coverage": extra_coverage or None,
        "acceptance_gate": {
            "rule": "strictly_better_log_loss_and_rps_same_validation_set",
            "metrics": list(GATE_METRICS),
            "baselines": list(baselines),
            "require_complete_extra_baselines": True,
            "standard_residual_refit_on_identical_advanced_sample": True,
        },
        # Parámetros de challenger para reproducibilidad. No se consumen en el feed.
        "challenger_params": _fit(rows),
        "affects_1x2": False,
        "promotion_status": "manual_future_pr_required",
    }
