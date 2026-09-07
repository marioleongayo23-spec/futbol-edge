"""P3.1/P3.2: histórico auditable de estadísticas finales por partido.

Conserva observaciones postpartido de API-Football y football-data.co.uk como
fuentes independientes, mantiene revisiones si un proveedor corrige un partido
y calcula un consenso por métrica. Una discrepancia nunca se resuelve de forma
silenciosa: queda marcada como ``conflict`` y ``usable=False``.

P3.2 permite además conservar ``xg`` cuando API-Football lo entrega de forma
pasiva. football-data.co.uk no aporta ese campo, por lo que xG queda identificado
como ``single_source`` y nunca se presenta falsamente como consenso multi-fuente.

Este archivo es evidencia histórica para evaluación/modelado futuro. No modifica
probabilidades, lambdas ni el dashboard.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import warnings
from zoneinfo import ZoneInfo

from .config import DATA_DIR, settings
from .ingest.football_data_uk import FootballDataUKClient, MatchStats
from .normalize import canonical_team

MADRID = ZoneInfo("Europe/Madrid")
SCHEMA = "final-stats-truth-v1"
OUTPUT = Path(DATA_DIR) / "final_stats_truth.json"
DASHBOARD = Path(DATA_DIR) / "dashboard.json"
SOURCE_API = "api_football"
SOURCE_FDUK = "football_data_uk"
STAT_KEYS = ("goals", "xg", "shots", "sot", "corners", "fouls", "yellows", "reds", "offsides")
LEAGUE_LABELS = {
    "LaLiga": "laliga",
    "LaLiga Hypermotion": "segunda",
    "Champions League": "champions",
}


def _canon(name: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(name or "").strip())


def _dt(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _num(value) -> float | int | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return int(out) if out.is_integer() else out


def _match_date(value) -> str | None:
    stamp = _dt(value)
    return stamp.astimezone(MADRID).date().isoformat() if stamp else None


def match_id(league: str, season: int, kickoff, home: str, away: str) -> str:
    date = _match_date(kickoff) or "unknown-date"
    material = "|".join((league, str(int(season)), date, _canon(home), _canon(away)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _normalise_stats(raw: dict | None) -> dict:
    out: dict[str, dict] = {}
    for stat in STAT_KEYS:
        row = (raw or {}).get(stat)
        if isinstance(row, dict):
            home, away = _num(row.get("home")), _num(row.get("away"))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            home, away = _num(row[0]), _num(row[1])
        else:
            continue
        if home is None or away is None or home < 0 or away < 0:
            continue
        out[stat] = {"home": home, "away": away, "total": _num(home + away)}
    return out


def _api_stats(match: dict) -> dict:
    source = str(match.get("statsRealSource") or "")
    if "API-Football" not in source:
        return {}
    return _normalise_stats(match.get("statsReal"))


def _fduk_stats(row: MatchStats) -> dict:
    return _normalise_stats(row.stats)


def _fduk_index(rows: list[MatchStats]) -> dict[tuple[str, str, str], list[MatchStats]]:
    out: dict[tuple[str, str, str], list[MatchStats]] = {}
    for row in rows or []:
        date = _match_date(row.kickoff)
        if not date:
            continue
        key = (_canon(row.home_team), _canon(row.away_team), date)
        out.setdefault(key, []).append(row)
    return out


def _observation(
    *,
    source: str,
    league: str,
    season: int,
    kickoff,
    home: str,
    away: str,
    stats: dict,
    captured_at: str,
    meta: dict | None = None,
) -> dict:
    return {
        "match_id": match_id(league, season, kickoff, home, away),
        "league": league,
        "season": int(season),
        "date": _match_date(kickoff),
        "kickoff": _dt(kickoff).isoformat() if _dt(kickoff) else None,
        "home": _canon(home),
        "away": _canon(away),
        "home_source_name": str(home),
        "away_source_name": str(away),
        "source": source,
        "captured_at": captured_at,
        "stats": _normalise_stats(stats),
        "meta": meta or {},
    }


def build_observations(
    matches: list[dict],
    *,
    league: str,
    season: int,
    fduk_rows: list[MatchStats] | None = None,
    captured_at: str,
) -> tuple[list[dict], dict]:
    """Empareja co.uk por equipos canónicos + fecha exacta; nunca fuzzy-match."""
    index = _fduk_index(fduk_rows or [])
    observations: list[dict] = []
    ambiguous = 0
    api_matches = 0
    fduk_matches = 0

    for match in matches:
        if not match.get("finished"):
            continue
        kickoff = match.get("kickoff") or match.get("date")
        date = _match_date(kickoff)
        home, away = str(match.get("home") or ""), str(match.get("away") or "")
        if not date or not home or not away:
            continue

        api = _api_stats(match)
        if api:
            observations.append(_observation(
                source=SOURCE_API,
                league=league,
                season=season,
                kickoff=kickoff,
                home=home,
                away=away,
                stats=api,
                captured_at=str(match.get("statsRealUpdatedAt") or captured_at),
                meta={
                    "fixture_id": ((match.get("alineacion") or {}).get("official_fixture_id")),
                    "source_label": match.get("statsRealSource"),
                },
            ))
            api_matches += 1

        key = (_canon(home), _canon(away), date)
        candidates = index.get(key) or []
        if len(candidates) == 1:
            stats = _fduk_stats(candidates[0])
            if stats:
                observations.append(_observation(
                    source=SOURCE_FDUK,
                    league=league,
                    season=season,
                    kickoff=kickoff,
                    home=home,
                    away=away,
                    stats=stats,
                    captured_at=captured_at,
                    meta={"referee": candidates[0].referee},
                ))
                fduk_matches += 1
        elif len(candidates) > 1:
            ambiguous += 1

    return observations, {
        "league": league,
        "season": int(season),
        "api_matches": api_matches,
        "football_data_uk_matches": fduk_matches,
        "ambiguous_football_data_uk_matches": ambiguous,
        "observations": len(observations),
    }


def empty_archive() -> dict:
    return {
        "schema": SCHEMA,
        "updated_at": None,
        "matches": {},
        "quality": {},
        "affects_1x2": False,
    }


def load_archive(path: str | Path = OUTPUT) -> dict:
    target = Path(path)
    if not target.exists():
        return empty_archive()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_archive()
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA or not isinstance(raw.get("matches"), dict):
        return empty_archive()
    raw.setdefault("updated_at", None)
    raw.setdefault("quality", {})
    raw["affects_1x2"] = False
    return raw


def _observation_digest(observation: dict) -> str:
    semantic = {
        "source": observation.get("source"),
        "league": observation.get("league"),
        "season": observation.get("season"),
        "date": observation.get("date"),
        "home": observation.get("home"),
        "away": observation.get("away"),
        "stats": observation.get("stats") or {},
        "meta": observation.get("meta") or {},
    }
    return hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _pair(row: dict | None) -> tuple[float | int, float | int] | None:
    if not isinstance(row, dict):
        return None
    home, away = _num(row.get("home")), _num(row.get("away"))
    return (home, away) if home is not None and away is not None else None


def reconcile_entry(entry: dict) -> dict:
    sources = entry.get("sources") or {}
    api = ((sources.get(SOURCE_API) or {}).get("latest") or {}).get("stats") or {}
    fduk = ((sources.get(SOURCE_FDUK) or {}).get("latest") or {}).get("stats") or {}
    consensus: dict[str, dict] = {}

    for stat in STAT_KEYS:
        api_pair, fduk_pair = _pair(api.get(stat)), _pair(fduk.get(stat))
        if api_pair and fduk_pair:
            if api_pair == fduk_pair:
                consensus[stat] = {
                    "status": "agreed",
                    "usable": True,
                    "home": api_pair[0],
                    "away": api_pair[1],
                    "sources": [SOURCE_API, SOURCE_FDUK],
                    "confidence": 1.0,
                }
            else:
                consensus[stat] = {
                    "status": "conflict",
                    "usable": False,
                    "sources": {
                        SOURCE_API: {"home": api_pair[0], "away": api_pair[1]},
                        SOURCE_FDUK: {"home": fduk_pair[0], "away": fduk_pair[1]},
                    },
                    "delta": {
                        "home": _num(api_pair[0] - fduk_pair[0]),
                        "away": _num(api_pair[1] - fduk_pair[1]),
                    },
                    "confidence": 0.0,
                }
        else:
            pair = api_pair or fduk_pair
            source = SOURCE_API if api_pair else SOURCE_FDUK if fduk_pair else None
            if pair and source:
                consensus[stat] = {
                    "status": "single_source",
                    "usable": True,
                    "home": pair[0],
                    "away": pair[1],
                    "sources": [source],
                    "confidence": 0.6,
                }

    statuses = {row.get("status") for row in consensus.values()}
    if "conflict" in statuses:
        status = "conflict"
    elif "agreed" in statuses:
        status = "verified_multi_source"
    elif consensus:
        status = "single_source"
    else:
        status = "empty"
    entry["consensus"] = consensus
    entry["status"] = status
    entry["affects_1x2"] = False
    return entry


def _quality(matches: dict[str, dict]) -> dict:
    source_matches = {SOURCE_API: 0, SOURCE_FDUK: 0}
    statuses: dict[str, int] = {}
    conflicts: dict[str, int] = {stat: 0 for stat in STAT_KEYS}
    usable: dict[str, int] = {stat: 0 for stat in STAT_KEYS}
    for entry in matches.values():
        for source in source_matches:
            if source in (entry.get("sources") or {}):
                source_matches[source] += 1
        status = str(entry.get("status") or "empty")
        statuses[status] = statuses.get(status, 0) + 1
        for stat, row in (entry.get("consensus") or {}).items():
            if row.get("status") == "conflict":
                conflicts[stat] = conflicts.get(stat, 0) + 1
            if row.get("usable"):
                usable[stat] = usable.get(stat, 0) + 1
    return {
        "matches": len(matches),
        "source_matches": source_matches,
        "statuses": statuses,
        "conflicts_by_stat": {key: value for key, value in conflicts.items() if value},
        "usable_by_stat": {key: value for key, value in usable.items() if value},
    }


def update_archive(archive: dict, observations: list[dict], *, updated_at: str) -> tuple[dict, dict]:
    out = deepcopy(archive if archive.get("schema") == SCHEMA else empty_archive())
    matches = out.setdefault("matches", {})
    added_revisions = 0
    unchanged = 0

    for observation in observations:
        if not observation.get("stats") or observation.get("source") not in {SOURCE_API, SOURCE_FDUK}:
            continue
        key = str(observation.get("match_id") or "")
        if not key:
            continue
        entry = matches.setdefault(key, {
            "match_id": key,
            "league": observation.get("league"),
            "season": observation.get("season"),
            "date": observation.get("date"),
            "kickoff": observation.get("kickoff"),
            "home": observation.get("home"),
            "away": observation.get("away"),
            "sources": {},
            "consensus": {},
            "status": "empty",
            "affects_1x2": False,
        })
        source = observation["source"]
        source_row = entry.setdefault("sources", {}).setdefault(source, {"latest": None, "history": []})
        digest = _observation_digest(observation)
        known = {
            _observation_digest(row)
            for row in (source_row.get("history") or [])
            if isinstance(row, dict)
        }
        if digest in known:
            unchanged += 1
        else:
            source_row.setdefault("history", []).append(deepcopy(observation))
            source_row["latest"] = deepcopy(observation)
            added_revisions += 1
        reconcile_entry(entry)

    out["quality"] = _quality(matches)
    if added_revisions:
        out["updated_at"] = updated_at
    out["affects_1x2"] = False
    return out, {
        "added_revisions": added_revisions,
        "unchanged_observations": unchanged,
        **out["quality"],
        "affects_1x2": False,
    }


def write_archive(path: str | Path, archive: dict) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(archive, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def refresh_truth_store(
    dashboard_path: str | Path = DASHBOARD,
    output_path: str | Path = OUTPUT,
    *,
    season: int | None = None,
    captured_at: str | None = None,
) -> dict:
    stamp = captured_at or datetime.now(timezone.utc).isoformat()
    actual_season = int(season or settings.season)
    try:
        payload = json.loads(Path(dashboard_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "dashboard_unavailable", "affects_1x2": False}
    matches = [row for row in (payload.get("matches") or []) if isinstance(row, dict)]
    observations: list[dict] = []
    source_audit = {}

    for label, league in LEAGUE_LABELS.items():
        league_matches = [row for row in matches if row.get("league") == label]
        if not league_matches:
            continue
        fduk_rows: list[MatchStats] = []
        if league in {"laliga", "segunda"}:
            try:
                fduk_rows = FootballDataUKClient().get_stats(league, actual_season)
            except Exception:
                fduk_rows = []
        rows, audit = build_observations(
            league_matches,
            league=league,
            season=actual_season,
            fduk_rows=fduk_rows,
            captured_at=stamp,
        )
        observations.extend(rows)
        source_audit[league] = audit

    previous = load_archive(output_path)
    updated, summary = update_archive(previous, observations, updated_at=stamp)
    if summary["added_revisions"]:
        write_archive(output_path, updated)
    return {
        "status": "updated" if summary["added_revisions"] else "no_change",
        "output": str(output_path),
        "source_audit": source_audit,
        **summary,
    }


def main() -> int:
    report = refresh_truth_store()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())