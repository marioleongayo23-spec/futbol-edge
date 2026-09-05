"""Score auditable de calidad de datos para un partido.

No modifica probabilidades ni inventa datos. Convierte la cobertura operativa
existente en una señal compacta para UI, ranking y gates de publicación.
"""
from __future__ import annotations

from typing import Any


# Pesos deliberadamente conservadores: el fixture es imprescindible, mientras
# que contexto, XI, cuotas y jugadores aumentan la calidad cuando están presentes.
_WEIGHTS = {
    "fixture": 20,
    "weather": 10,
    "absences": 15,
    "lineup_probable": 15,
    "lineup_official": 15,
    "odds": 15,
    "players": 10,
}


def _state_score(item: dict[str, Any] | None) -> float:
    if not isinstance(item, dict):
        return 0.0
    state = str(item.get("state") or "").casefold()
    if state == "ok":
        return 1.0
    # Evidence and collection schedules are separate concepts. Estimated or
    # partial data is useful but not equivalent to a verified source.
    if state == "estimated":
        return 0.45
    if state == "partial":
        return 0.55
    if state in {"scheduled", "waiting"}:
        # Not due yet is a scheduling fact, never verified evidence.
        return 0.0
    return 0.0


def calculate_match_quality(match: dict[str, Any], coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic 0-100 quality score and publication tier."""
    coverage = coverage or match.get("coverage") or {}
    items = coverage.get("items") or {}

    scores: dict[str, float] = {
        key: _state_score(items.get(key)) for key in _WEIGHTS if key != "players"
    }

    lineup = match.get("alineacion") or {}
    home = len(lineup.get("local") or [])
    away = len(lineup.get("visitante") or [])
    players = match.get("player_stats") or match.get("players")
    if isinstance(players, dict) and players:
        scores["players"] = 1.0
    elif home == 11 and away == 11:
        scores["players"] = 0.5
    else:
        scores["players"] = 0.0

    weighted = sum(scores[key] * weight for key, weight in _WEIGHTS.items())
    total = sum(_WEIGHTS.values())
    score = round(100.0 * weighted / total, 1)

    required_missing = list(coverage.get("missing_required") or [])
    if not isinstance(required_missing, list):
        required_missing = []

    # A high score cannot override a missing fixture or a required pre-kickoff
    # source. This keeps "confidence" honest instead of turning completeness
    # into a cosmetic badge.
    if scores["fixture"] < 1.0:
        tier = "blocked"
    elif required_missing:
        tier = "limited" if score >= 60 else "insufficient"
    elif score >= 85:
        tier = "high"
    elif score >= 70:
        tier = "medium"
    elif score >= 50:
        tier = "limited"
    else:
        tier = "insufficient"

    return {
        "score": score,
        "tier": tier,
        "verified": round(sum(scores[key] * _WEIGHTS[key] for key in scores) / total, 3),
        "required_missing": required_missing,
        "components": {key: round(value * 100, 1) for key, value in scores.items()},
    }
