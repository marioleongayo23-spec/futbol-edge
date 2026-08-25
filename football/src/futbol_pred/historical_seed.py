"""Semilla walk-forward de temporada anterior para calibración desde jornada 1."""
from __future__ import annotations

import math
import warnings

from .backtest import DixonColesPredictor, walk_forward
from .backtest.metrics import aggregate, calibration_table
from .config import LEAGUE_META
from .ingest.football_data_uk import FootballDataUKClient
from .market_calibration import _blend, _fit, market_candidate_beats_model
from .normalize import canonical_team
from .pipeline import fixtures_to_matches, get_fixtures
from .value.odds import remove_vig


def _canon(name: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(name)


def _quality(rows: list[tuple[dict[str, float], str]]) -> dict | None:
    if not rows:
        return None
    metrics = aggregate(rows)
    return {
        "n": metrics["n"],
        "log_loss": round(metrics["log_loss"], 4),
        "brier": round(metrics["brier"], 4),
        "rps": round(metrics["rps"], 4),
        "accuracy": round(metrics["accuracy"] * 100, 1),
    }


def _fair_1x2(prices: dict) -> dict[str, float] | None:
    try:
        odds = [float(prices[key]) for key in ("1", "X", "2")]
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 1 for value in odds):
        return None
    fair = remove_vig(odds)
    return dict(zip(("1", "X", "2"), fair))


def prior_season_seed(league: str, current_season: int) -> dict | None:
    """Walk-forward del año anterior + cierre real; sin datos suficientes, None."""
    if league not in {"laliga", "segunda"}:
        return None
    previous = int(current_season) - 1
    try:
        fixtures = get_fixtures(league, season=previous)
        tpr = LEAGUE_META.get(league, {}).get("teams_per_round")
        matches = fixtures_to_matches(fixtures, teams_per_round=tpr)
        closing_rows = FootballDataUKClient().get_historical_closing_odds(league, previous)
    except Exception:
        return None
    if len(matches) < 40 or not closing_rows:
        return None

    closing = {
        (_canon(row["home"]), _canon(row["away"])): row["closing_odds"].get("1x2")
        for row in closing_rows if row.get("closing_odds")
    }
    for match in matches:
        prices = closing.get((_canon(match["home"]), _canon(match["away"])))
        if prices:
            match["odds"] = prices

    try:
        result = walk_forward(matches, DixonColesPredictor(min_matches=30), min_train_rounds=3)
    except Exception:
        return None

    rows = []
    model_rows = []
    market_rows = []
    for record in result.records:
        model = record.get("probs")
        market = _fair_1x2(record.get("odds") or {})
        actual = record.get("actual")
        if model and market and actual in {"1", "X", "2"}:
            rows.append((model, market, actual))
            model_rows.append((model, actual))
            market_rows.append((market, actual))
    if len(rows) < 30:
        return None

    split = max(20, min(len(rows) - 10, round(len(rows) * 0.70)))
    train, validation = rows[:split], rows[split:]
    weight, temp = _fit(train)
    candidate_rows = [(_blend(model, market, weight, temp), actual) for model, market, actual in validation]
    champion_rows = [(model, actual) for model, _, actual in validation]
    candidate = aggregate(candidate_rows)
    champion = aggregate(champion_rows)
    accepted = market_candidate_beats_model(candidate, champion)
    prod_weight, prod_temp = _fit(rows)
    blended_all = [(_blend(model, market, prod_weight, prod_temp), actual) for model, market, actual in rows]

    return {
        "league": league,
        "scope": "historical_seed",
        "evaluation_season": previous,
        "current_season": current_season,
        "source": "walk-forward Dixon-Coles + football-data.co.uk historical closing odds",
        "cost": "football-data.co.uk CSV: sin API key; coste monetario 0",
        "market_calibration": {
            "accepted": accepted,
            "n": len(rows),
            "n_validation": len(validation),
            "validation": candidate,
            "champion": champion,
            "acceptance_gate": {"rule": "strictly_better_than_published_model", "metrics": ["log_loss", "rps"]},
            "production": {
                "model_weight": round(prod_weight, 4),
                "market_weight": round(1.0 - prod_weight, 4),
                "temperature": round(prod_temp, 4),
            },
            "seeded_from_previous_season": True,
            "evaluation_season": previous,
        },
        "probability_quality": {
            "model_only": _quality(model_rows),
            "market": _quality(market_rows),
            "published_seed": _quality(blended_all),
            "reliability_1": calibration_table(blended_all, "1", bins=10),
            "reliability_X": calibration_table(blended_all, "X", bins=10),
            "reliability_2": calibration_table(blended_all, "2", bins=10),
        },
    }


def build_historical_seeds(current_season: int) -> dict:
    out = {}
    for league in ("laliga", "segunda"):
        seed = prior_season_seed(league, current_season)
        if seed:
            out[league] = seed
    return out
