"""Aprende cuánto confiar en modelo vs mercado usando snapshots reales."""

from __future__ import annotations

import math

from scipy.optimize import minimize_scalar

from .backtest.ensemble import candidate_beats_all_baselines, temperature_scale
from .backtest.metrics import aggregate
from .prediction_snapshots import latest_pre_match_snapshot

SIGNS = ("1", "X", "2")
GATE_METRICS = ("log_loss", "rps")


def _dict(values) -> dict[str, float] | None:
    if isinstance(values, list) and len(values) == 3:
        raw = {key: float(values[i]) / 100.0 for i, key in enumerate(SIGNS)}
    elif isinstance(values, dict) and all(key in values for key in SIGNS):
        raw = {key: float(values[key]) for key in SIGNS}
    else:
        return None
    total = sum(raw.values())
    return {key: raw[key] / total for key in SIGNS} if total > 0 else None


def _blend(model: dict[str, float], market: dict[str, float], weight: float, temp: float) -> dict[str, float]:
    weight = max(0.0, min(1.0, weight))
    mixed = {key: weight * model[key] + (1.0 - weight) * market[key] for key in SIGNS}
    return temperature_scale(mixed, temp)


def _loss(rows, weight: float, temp: float) -> float:
    if not rows:
        return float("inf")
    return sum(-math.log(max(1e-12, _blend(model, market, weight, temp)[actual]))
               for model, market, actual in rows) / len(rows)


def _fit(rows) -> tuple[float, float]:
    weight, temp = 0.65, 1.0
    for _ in range(3):
        result_w = minimize_scalar(lambda value: _loss(rows, value, temp), bounds=(0.05, 0.95), method="bounded")
        if result_w.success:
            weight = float(result_w.x)
        result_t = minimize_scalar(lambda value: _loss(rows, weight, value), bounds=(0.65, 1.8), method="bounded")
        if result_t.success:
            temp = float(result_t.x)
    return weight, temp


def market_candidate_beats_model(candidate: dict, champion: dict) -> bool:
    """La mezcla solo se promociona si mejora estrictamente al modelo publicado."""

    return candidate_beats_all_baselines(candidate, {"model": champion})


def learn_market_calibration(matches: list[dict], league: str) -> dict | None:
    rows = []
    selected = sorted(
        (match for match in matches if match.get("league") == league and match.get("finished") and match.get("result")),
        key=lambda match: str(match.get("kickoff") or ""),
    )
    for match in selected:
        snapshot = latest_pre_match_snapshot(match)
        if not snapshot:
            continue
        model = _dict(snapshot.get("model_probs"))
        odds = snapshot.get("odds")
        market = (
            _dict(((odds.get("1x2") or {}).get("fair")))
            if isinstance(odds, dict) else None
        )
        result = match["result"]
        actual = "1" if result[0] > result[1] else "2" if result[0] < result[1] else "X"
        if model and market:
            rows.append((model, market, actual))
    if len(rows) < 30:
        return None

    split = max(20, min(len(rows) - 10, round(len(rows) * 0.70)))
    train, validation = rows[:split], rows[split:]
    weight, temp = _fit(train)
    candidate = [(_blend(model, market, weight, temp), actual) for model, market, actual in validation]
    champion = [(model, actual) for model, _, actual in validation]
    candidate_metrics = aggregate(candidate)
    champion_metrics = aggregate(champion)
    accepted = market_candidate_beats_model(candidate_metrics, champion_metrics)
    prod_weight, prod_temp = _fit(rows)
    return {
        "accepted": accepted,
        "n": len(rows),
        "n_validation": len(validation),
        "validation": candidate_metrics,
        "champion": champion_metrics,
        "acceptance_gate": {
            "rule": "strictly_better_than_published_model",
            "metrics": list(GATE_METRICS),
        },
        "production": {
            "model_weight": round(prod_weight, 4),
            "market_weight": round(1.0 - prod_weight, 4),
            "temperature": round(prod_temp, 4),
        },
    }
