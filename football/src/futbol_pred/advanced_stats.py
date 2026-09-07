"""Snapshots avanzados xG/PSxG consumibles sin scraping en producción.

La adquisición (FBref/Understat u otra fuente) ocurre fuera del cron y publica un
artefacto versionado. Producción solo lee snapshots cuyo ``available_at`` sea
estrictamente anterior al cutoff del partido. Esta capa es candidate/context-only:
NO modifica Dixon-Coles, lambdas ni ``probs``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import warnings

from .config import DATA_DIR
from .normalize import canonical_team

SCHEMA = "advanced-stats-snapshot-v1"
ARCHIVE_SCHEMA = "advanced-stats-archive-v1"
DEFAULT_PATH = Path(DATA_DIR) / "advanced_stats_snapshots.json"
KEEPER_PRIOR_MINUTES = 900.0


def _dt(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canon(team: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(team or ""))


def shrink_rate(
    rate: float | None,
    minutes: float | None,
    *,
    league_rate: float = 0.0,
    prior_minutes: float = KEEPER_PRIOR_MINUTES,
) -> float | None:
    """Encoge una tasa /90 de portero hacia la media de liga según minutos."""
    value, mins = _num(rate), _num(minutes)
    prior = max(0.0, float(prior_minutes))
    if value is None or mins is None or mins < 0:
        return None
    weight = mins / (mins + prior) if mins + prior > 0 else 0.0
    return weight * value + (1.0 - weight) * float(league_rate)


def validate_snapshot(snapshot: dict) -> list[str]:
    issues: list[str] = []
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
        return ["schema_invalid"]
    if _dt(snapshot.get("available_at")) is None:
        issues.append("available_at_invalid")
    if not str(snapshot.get("source") or "").strip():
        issues.append("source_missing")
    if not str(snapshot.get("league") or "").strip():
        issues.append("league_missing")
    try:
        int(snapshot.get("season"))
    except (TypeError, ValueError):
        issues.append("season_invalid")
    teams = snapshot.get("teams")
    if not isinstance(teams, dict):
        issues.append("teams_invalid")
        return issues
    seen: set[str] = set()
    for raw_team, row in teams.items():
        canon = _canon(raw_team)
        if not canon:
            issues.append("team_empty")
            continue
        if canon in seen:
            issues.append(f"team_duplicate:{canon}")
        seen.add(canon)
        if not isinstance(row, dict):
            issues.append(f"team_row_invalid:{canon}")
            continue
        for field in ("xg_for90", "npxg_for90", "xg_against90", "npxg_against90"):
            if field in row and row[field] is not None and _num(row[field]) is None:
                issues.append(f"{field}_invalid:{canon}")
        keepers = row.get("goalkeepers") or []
        if not isinstance(keepers, list):
            issues.append(f"goalkeepers_invalid:{canon}")
    return issues


def normalise_snapshot(snapshot: dict) -> dict:
    """Devuelve snapshot canónico; colisiones de equipo se rechazan."""
    issues = validate_snapshot(snapshot)
    if issues:
        raise ValueError(";".join(issues))
    out = deepcopy(snapshot)
    teams: dict[str, dict] = {}
    for raw_team, raw_row in snapshot.get("teams", {}).items():
        canon = _canon(raw_team)
        if canon in teams:
            raise ValueError(f"team_duplicate:{canon}")
        row = deepcopy(raw_row)
        row["team_source_name"] = row.get("team_source_name") or raw_team
        keepers = []
        for keeper in row.get("goalkeepers") or []:
            if not isinstance(keeper, dict):
                continue
            item = deepcopy(keeper)
            for field in ("minutes", "psxg90", "psxg_plus_minus90"):
                if field in item:
                    item[field] = _num(item[field])
            keepers.append(item)
        row["goalkeepers"] = keepers
        teams[canon] = row
    out["teams"] = teams
    out["season"] = int(out["season"])
    return out


def load_archive(path: str | Path = DEFAULT_PATH) -> dict:
    target = Path(path)
    if not target.exists():
        return {"schema": ARCHIVE_SCHEMA, "snapshots": []}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": ARCHIVE_SCHEMA, "snapshots": []}
    snapshots = raw.get("snapshots") if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    valid = []
    for snapshot in snapshots or []:
        try:
            valid.append(normalise_snapshot(snapshot))
        except (TypeError, ValueError):
            continue
    return {"schema": ARCHIVE_SCHEMA, "snapshots": valid}


def latest_snapshot_as_of(
    archive: dict | list,
    league: str,
    season: int,
    cutoff,
) -> dict | None:
    cutoff_dt = _dt(cutoff)
    if cutoff_dt is None:
        return None
    snapshots = archive.get("snapshots") if isinstance(archive, dict) else archive
    candidates = []
    for raw in snapshots or []:
        try:
            snapshot = normalise_snapshot(raw)
        except (TypeError, ValueError):
            continue
        available = _dt(snapshot.get("available_at"))
        if (
            available is not None
            and available < cutoff_dt
            and snapshot.get("league") == league
            and int(snapshot.get("season")) == int(season)
        ):
            candidates.append((available, snapshot))
    return deepcopy(max(candidates, key=lambda item: item[0])[1]) if candidates else None


def _primary_keeper(team_row: dict, league_keeper_rate: float = 0.0) -> dict | None:
    keepers = [row for row in (team_row.get("goalkeepers") or []) if isinstance(row, dict)]
    if not keepers:
        return None
    keeper = max(keepers, key=lambda row: _num(row.get("minutes")) or 0.0)
    minutes = _num(keeper.get("minutes")) or 0.0
    raw = _num(keeper.get("psxg_plus_minus90"))
    shrunk = shrink_rate(raw, minutes, league_rate=league_keeper_rate)
    return {
        "player": keeper.get("player"),
        "minutes": round(minutes, 1),
        "psxg90": _num(keeper.get("psxg90")),
        "psxg_plus_minus90_raw": raw,
        "psxg_plus_minus90_shrunk": round(shrunk, 4) if shrunk is not None else None,
        "prior_minutes": KEEPER_PRIOR_MINUTES,
    }


def match_context(snapshot: dict | None, home: str, away: str) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    teams = snapshot.get("teams") or {}
    home_row, away_row = teams.get(_canon(home)), teams.get(_canon(away))
    if not isinstance(home_row, dict) or not isinstance(away_row, dict):
        return None
    league_rate = _num(snapshot.get("league_keeper_psxg_plus_minus90")) or 0.0

    def side(row: dict) -> dict:
        return {
            field: _num(row.get(field))
            for field in ("xg_for90", "npxg_for90", "xg_against90", "npxg_against90")
            if row.get(field) is not None
        } | {
            "matches": int(_num(row.get("matches")) or 0),
            "goalkeeper": _primary_keeper(row, league_rate),
        }

    return {
        "schema": SCHEMA,
        "status": "candidate_context_only",
        "source": snapshot.get("source"),
        "source_version": snapshot.get("source_version"),
        "available_at": snapshot.get("available_at"),
        "generated_at": snapshot.get("generated_at"),
        "league": snapshot.get("league"),
        "season": snapshot.get("season"),
        "home": side(home_row),
        "away": side(away_row),
        "gate": "historical_as_of_snapshots + rolling_walk_forward_vs_champion_pending",
        "affects_1x2": False,
    }


def attach_advanced_context(
    matches: list[dict],
    archive: dict | list,
    *,
    season: int,
    now,
    league_labels: dict[str, str] | None = None,
) -> int:
    """Adjunta contexto usando cutoff=min(now,kickoff), nunca información futura."""
    labels = league_labels or {
        "LaLiga": "laliga",
        "LaLiga Hypermotion": "segunda",
        "Champions League": "champions",
    }
    now_dt = _dt(now)
    if now_dt is None:
        return 0
    attached = 0
    for match in matches:
        league = labels.get(str(match.get("league") or ""))
        kickoff = _dt(match.get("kickoff"))
        if not league or kickoff is None:
            continue
        cutoff = min(now_dt, kickoff)
        snapshot = latest_snapshot_as_of(archive, league, season, cutoff)
        context = match_context(snapshot, str(match.get("home") or ""), str(match.get("away") or ""))
        if context:
            match["advanced_stats"] = context
            attached += 1
    return attached
