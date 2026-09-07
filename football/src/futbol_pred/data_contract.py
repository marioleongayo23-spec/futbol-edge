"""Canonical identity and provenance contract for Fútbol Edge data.

This module is deliberately provider-agnostic. A football match must keep the
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
LIVE_STATUSES = {"LIVE", "IN_PLAY", "IN PLAY", "1H", "2H", "HT", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT"}
LEAGUE_UIDS = {
    "LaLiga": "laliga",
    "LaLiga Hypermotion": "segunda",
    "Champions League": "champions",
}


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
    same kickoff with different timezone offsets. Source/provider ids are
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
    signal was actually available to Fútbol Edge. It must not be replaced by a
    later feed-generation timestamp when a true source timestamp is known.
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


def _source_id_from_legacy(match: dict) -> str | None:
    """Recover provider id from legacy ``<source>-<id>`` without guessing."""
    source = str(match.get("source") or "").strip()
    legacy_id = str(match.get("id") or "").strip()
    prefix = source + "-"
    if source and legacy_id.startswith(prefix) and len(legacy_id) > len(prefix):
        return legacy_id[len(prefix):]
    return None


def _phase_for_match(match: dict) -> str:
    if match.get("finished"):
        return "postmatch"
    status = str(match.get("status") or "").upper().replace("-", "_")
    return "live" if status in LIVE_STATUSES else "prematch"


def _quality_for_source(source: str) -> str:
    normalized = str(source or "").casefold()
    if any(token in normalized for token in ("api-football", "football-data", "rfef", "open-meteo")):
        return "verified"
    if normalized:
        return "observed"
    return "fallback"


def enrich_feed_contract(payload: dict) -> int:
    """Add canonical identity and conservative provenance to every feed match.

    This is intentionally an additive boundary migration: legacy ``id`` remains
    untouched for UI compatibility. When a source does not expose its true
    publication timestamp, the feed ingestion timestamp is used as
    ``available_at``. That is conservative (possibly later than reality) and
    therefore leakage-safe.
    """
    if not isinstance(payload, dict):
        return 0
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return 0
    season = payload.get("season")
    generated_at = payload.get("generated_at")
    enriched = 0
    for match in matches:
        if not isinstance(match, dict):
            continue
        try:
            league = LEAGUE_UIDS.get(str(match.get("league")), str(match.get("league") or ""))
            match_uid = canonical_match_uid(
                league=league,
                season=int(season),
                home_team=str(match.get("home") or ""),
                away_team=str(match.get("away") or ""),
                kickoff=str(match.get("kickoff") or ""),
            )
        except (TypeError, ValueError, KeyError):
            continue
        match["match_uid"] = match_uid

        observed_at = match.get("updatedAt") or generated_at
        available_at = match.get("source_available_at") or observed_at
        if not available_at:
            enriched += 1
            continue
        source = str(match.get("source") or "legacy-feed")
        source_id = match.get("source_id") or _source_id_from_legacy(match)
        phase = _phase_for_match(match)
        quality = _quality_for_source(source)
        provenance = match.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
            match["provenance"] = provenance
        provenance["fixture"] = source_observation(
            source=source,
            source_id=source_id,
            available_at=available_at,
            observed_at=observed_at,
            phase=phase,
            quality=quality,
        )
        if match.get("finished") and isinstance(match.get("result"), list):
            provenance["result"] = source_observation(
                source=source,
                source_id=source_id,
                available_at=available_at,
                observed_at=observed_at,
                phase="postmatch",
                quality=quality,
            )
        enriched += 1
    return enriched


def dedupe_feed_by_match_uid(payload: dict) -> int:
    """Merge duplicate provider observations of the same canonical match.

    The richer copy wins, but source references from all copies are retained in
    ``source_refs`` for auditability. Legacy ``id`` is left unchanged on the
    winning row so existing frontend links remain stable.
    """
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if not isinstance(matches, list):
        return 0

    def richness(match: dict) -> int:
        return sum(1 for value in match.values() if value not in (None, "", [], {}))

    order: list = []
    index_by_uid: dict[str, int] = {}
    removed = 0
    for match in matches:
        if not isinstance(match, dict) or not match.get("match_uid"):
            order.append(match)
            continue
        uid = str(match["match_uid"])
        source = str(match.get("source") or "unknown")
        source_id = match.get("source_id") or _source_id_from_legacy(match)
        refs = dict(match.get("source_refs") or {})
        if source_id is not None:
            refs[source] = str(source_id)
        match["source_refs"] = refs
        if uid not in index_by_uid:
            index_by_uid[uid] = len(order)
            order.append(match)
            continue

        removed += 1
        idx = index_by_uid[uid]
        existing = order[idx]
        existing_refs = dict(existing.get("source_refs") or {}) if isinstance(existing, dict) else {}
        existing_refs.update(refs)
        if isinstance(existing, dict) and richness(match) > richness(existing):
            match["source_refs"] = existing_refs
            order[idx] = match
        elif isinstance(existing, dict):
            existing["source_refs"] = existing_refs

    if removed:
        payload["matches"] = order
        counts = payload.get("counts")
        if isinstance(counts, dict):
            dicts = [m for m in order if isinstance(m, dict)]
            counts["total"] = len(order)
            counts["jugados"] = sum(1 for m in dicts if m.get("finished"))
            counts["proximos"] = sum(1 for m in dicts if not m.get("finished"))
            counts["con_prediccion"] = sum(
                1 for m in dicts if m.get("engine") in {"dixon-coles", "ensemble", "residual"}
            )
    return removed
