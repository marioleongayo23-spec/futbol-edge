"""Canonical identity and provenance contract for Fútbol Edge data.

This module is deliberately provider-agnostic.  A football match must keep the
same ``match_uid`` regardless of which adapter observed it, while every source
observation keeps its own provider id and availability timestamp.

The contract is the foundation for the historical feature store: features may
only be used by a prediction when ``available_at <= prediction_as_of``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from zoneinfo import ZoneInfo

from .normalize import canonical_team

MADRID = ZoneInfo("Europe/Madrid")
VALID_PHASES = {"prematch", "live", "postmatch"}
VALID_QUALITIES = {"official", "verified", "observed", "estimated", "fallback"}


def _slug(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return text or "unknown"


def _aware(value: datetime) -> datetime:
    """Return an aware datetime without silently changing a known timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=MADRID)
    return value


def iso_utc(value: datetime | str) -> str:
    """Normalize timestamps to UTC ISO-8601 for causal comparisons."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("timestamp must be datetime or ISO string")
    return _aware(parsed).astimezone(timezone.utc).isoformat()


def canonical_match_uid(
    league: str,
    season: int,
    home_team: str,
    away_team: str,
    kickoff: datetime | str,
) -> str:
    """Build a provider-independent match identity.

    The local Madrid calendar date is part of the identity to disambiguate cup
    rematches while preserving the same id across providers that express the
    same kickoff with different timezone offsets.  Source/provider ids are
    intentionally excluded.
    """
    if not league:
        raise ValueError("league is required")
    try:
        season_int = int(season)
    except (TypeError, ValueError) as exc:
        raise ValueError("season must be an integer") from exc
    if not (2000 <= season_int <= 2100):
        raise ValueError("season outside supported range")
    if not home_team or not away_team:
        raise ValueError("home_team and away_team are required")

    home = canonical_team(home_team)
    away = canonical_team(away_team)
    if home == away:
        raise ValueError("home_team and away_team resolve to the same canonical team")

    if isinstance(kickoff, str):
        kickoff_dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    elif isinstance(kickoff, datetime):
        kickoff_dt = kickoff
    else:
        raise TypeError("kickoff must be datetime or ISO string")
    local_day = _aware(kickoff_dt).astimezone(MADRID).date().strftime("%Y%m%d")

    return ":".join(
        (
            _slug(league),
            str(season_int),
            local_day,
            _slug(home),
            _slug(away),
        )
    )


def source_observation(
    *,
    source: str,
    source_id: object | None,
    available_at: datetime | str,
    phase: str = "prematch",
    quality: str = "observed",
    observed_at: datetime | str | None = None,
) -> dict:
    """Create a normalized provenance record for one source observation.

    ``available_at`` is the causal timestamp: the earliest time at which the
    signal was actually available to Fútbol Edge.  It must not be replaced by a
    later feed-generation timestamp.
    """
    source_name = str(source or "").strip()
    if not source_name:
        raise ValueError("source is required")
    phase = str(phase or "").casefold()
    quality = str(quality or "").casefold()
    if phase not in VALID_PHASES:
        raise ValueError(f"invalid phase: {phase}")
    if quality not in VALID_QUALITIES:
        raise ValueError(f"invalid quality: {quality}")

    out = {
        "source": source_name,
        "source_id": None if source_id is None else str(source_id),
        "available_at": iso_utc(available_at),
        "phase": phase,
        "quality": quality,
    }
    if observed_at is not None:
        out["observed_at"] = iso_utc(observed_at)
    return out


def is_available_as_of(observation: dict, prediction_as_of: datetime | str) -> bool:
    """True only when a signal existed at or before the prediction snapshot."""
    available = observation.get("available_at") if isinstance(observation, dict) else None
    if not available:
        return False
    return datetime.fromisoformat(iso_utc(available)) <= datetime.fromisoformat(iso_utc(prediction_as_of))
