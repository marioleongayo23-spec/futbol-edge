"""Source priority and causal selection rules for Fútbol Edge.

A source is never selected only because it is newer.  Selection is domain
specific and constrained by ``available_at`` so a post-match/live observation
cannot leak into a pre-match prediction snapshot.
"""
from __future__ import annotations

from datetime import datetime

from .data_contract import iso_utc, is_available_as_of

# Lower is better. Unknown providers are allowed, but rank after explicit ones.
SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "calendar": (
        "football-data",
        "API-Football",
        "openfootball",
        "football-data.co.uk",
    ),
    "result": (
        "API-Football",
        "football-data",
        "football-data.co.uk",
        "openfootball",
    ),
    "team_stats": (
        "football-data.co.uk",
        "API-Football",
        "FBref",
    ),
    "xg": (
        "FBref",
        "API-Football",
        "football-data.co.uk",
    ),
    "lineup": (
        "API-Football",
        "official-club",
        "media",
        "ai-estimate",
    ),
    "absences": (
        "API-Football",
        "official-club",
        "media",
        "ai-estimate",
    ),
    "referee": (
        "RFEF",
        "API-Football",
        "football-data.co.uk",
        "media",
    ),
    "odds": (
        "The Odds API",
        "football-data.co.uk",
    ),
    "weather": (
        "Open-Meteo",
    ),
    "player_stats": (
        "FBref",
        "API-Football",
        "football-data.org",
        "AS",
    ),
}

QUALITY_PRIORITY = {
    "official": 0,
    "verified": 1,
    "observed": 2,
    "estimated": 3,
    "fallback": 4,
}

PHASE_PRIORITY = {"prematch": 0, "live": 1, "postmatch": 2}


def _source_rank(domain: str, source: str) -> int:
    providers = SOURCE_PRIORITY.get(str(domain or "").casefold(), ())
    try:
        return providers.index(str(source or ""))
    except ValueError:
        return len(providers) + 100


def observation_rank(domain: str, observation: dict) -> tuple:
    """Stable best-first ranking for already-causal observations."""
    source = str(observation.get("source") or "")
    quality = str(observation.get("quality") or "fallback").casefold()
    phase = str(observation.get("phase") or "postmatch").casefold()
    available = observation.get("available_at")
    # Newer observations from equally trusted sources win, hence negative epoch.
    try:
        epoch = datetime.fromisoformat(iso_utc(available)).timestamp()
    except (TypeError, ValueError):
        epoch = 0.0
    return (
        PHASE_PRIORITY.get(phase, 99),
        QUALITY_PRIORITY.get(quality, 99),
        _source_rank(domain, source),
        -epoch,
        source.casefold(),
        str(observation.get("source_id") or ""),
    )


def choose_best_observation(
    domain: str,
    observations: list[dict],
    *,
    prediction_as_of: datetime | str,
    allowed_phases: set[str] | None = None,
) -> dict | None:
    """Choose the best observation that existed at prediction time.

    For pre-match feature building call with ``allowed_phases={"prematch"}``.
    Post-match truth pipelines may allow all phases explicitly.
    """
    phases = {str(value).casefold() for value in allowed_phases} if allowed_phases else None
    eligible = []
    for observation in observations or []:
        if not isinstance(observation, dict):
            continue
        phase = str(observation.get("phase") or "").casefold()
        if phases is not None and phase not in phases:
            continue
        if not is_available_as_of(observation, prediction_as_of):
            continue
        eligible.append(observation)
    if not eligible:
        return None
    return min(eligible, key=lambda row: observation_rank(domain, row))
