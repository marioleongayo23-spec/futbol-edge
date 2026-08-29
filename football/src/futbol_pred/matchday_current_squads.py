"""Sincronización autoritativa de plantillas actuales para partidos próximos.

API-Football ``/players/squads`` representa la plantilla registrada actual y no
acepta temporada. Esta capa evita que ``previous.players`` conserve fichajes/salidas
de campañas anteriores y usa esa plantilla como barrera de coherencia para XI no
oficiales.

Política de cuota:
- solo equipos con partido entre -3h y +36h;
- roster válido durante 12h;
- máximo 8 equipos nuevos por ciclo;
- ids de equipo se resuelven en una sola llamada ``/teams`` por liga/temporada.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json

from .config import DATA_DIR, LEAGUES
from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, _aware, _parse
from .ingest.api_football import ApiFootballClient

OUTPUT = DATA_DIR / "dashboard.json"
ROSTER_TTL_HOURS = 12
WINDOW_PAST_HOURS = 3
WINDOW_FUTURE_HOURS = 36
MAX_NEW_TEAMS_PER_CYCLE = 8


def _season_start(now_local: datetime) -> int:
    return now_local.year if now_local.month >= 7 else now_local.year - 1


def _league_key(label: str | None) -> str:
    text = str(label or "").casefold()
    if "hypermotion" in text or "segunda" in text:
        return "segunda"
    if "champions" in text or "ucl" in text:
        return "champions"
    return "laliga"


def _key(value: str | None) -> str:
    return ApiFootballClient._team_key(str(value or ""))


def _name_key(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").casefold().strip() if ch.isalnum())


def _same_team(left: str | None, right: str | None) -> bool:
    a, b = _key(left), _key(right)
    return bool(a and b and (a == b or a in b or b in a))


def _age_hours(value, now_local: datetime) -> float | None:
    stamp = _parse(value)
    if stamp is None:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 3600.0)


def _target_matches(payload: dict, now_local: datetime) -> list[dict]:
    out = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if kickoff is None:
            continue
        hours = (kickoff - now_local).total_seconds() / 3600.0
        if -WINDOW_PAST_HOURS <= hours <= WINDOW_FUTURE_HOURS:
            out.append(match)
    return out


def _bucket(payload: dict, league: str) -> dict:
    labels = {"laliga": "LaLiga", "segunda": "LaLiga Hypermotion", "champions": "Champions League"}
    players = payload.setdefault("players", {})
    return players.setdefault(league, {"label": labels.get(league, league), "rankings": {}, "players": []})


def _cached_squad(payload: dict, league: str, team: str, now_local: datetime) -> list[dict]:
    rows = (_bucket(payload, league).get("players") or [])
    squad = []
    ages = []
    for row in rows:
        if not isinstance(row, dict) or not _same_team(row.get("team"), team):
            continue
        if not row.get("current_squad_member"):
            continue
        age = _age_hours(row.get("current_squad_checked_at"), now_local)
        if age is None:
            continue
        ages.append(age)
        squad.append({
            "name": row.get("player"),
            "position": row.get("position") or row.get("api_position") or "",
            "player_id": row.get("player_id"),
            "number": row.get("number"),
            "photo": (row.get("profile") or {}).get("photo") if isinstance(row.get("profile"), dict) else row.get("photo"),
        })
    if len(squad) >= 11 and ages and max(ages) <= ROSTER_TTL_HOURS:
        return [row for row in squad if row.get("name")]
    return []


def _resolve_team_ids(client: ApiFootballClient, league: str, teams: list[str], season: int) -> dict[str, int]:
    if client.offline or not teams:
        return {}
    try:
        rows = client._get("teams", {"league": LEAGUES[league], "season": season}).get("response") or []
    except Exception:
        return {}
    candidates = []
    for row in rows:
        team = row.get("team") or {}
        if team.get("id") and team.get("name"):
            candidates.append((str(team["name"]), int(team["id"])))
    out = {}
    for wanted in teams:
        wk = _key(wanted)
        exact = next((team_id for name, team_id in candidates if _key(name) == wk), None)
        if exact:
            out[wanted] = exact
            continue
        best = None
        for name, team_id in candidates:
            score = SequenceMatcher(None, wk, _key(name)).ratio()
            if best is None or score > best[0]:
                best = (score, team_id)
        if best and best[0] >= 0.68:
            out[wanted] = best[1]
    return out


def _fetch_squad(client: ApiFootballClient, team_id: int) -> list[dict]:
    try:
        response = client._get("players/squads", {"team": int(team_id)}).get("response") or []
    except Exception:
        return []
    players = (response[0].get("players") or []) if response else []
    out = []
    for raw in players:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "position": str(raw.get("position") or "").strip(),
            "player_id": raw.get("id"),
            "number": raw.get("number"),
            "age": raw.get("age"),
            "photo": raw.get("photo"),
        })
    return out


def _sync_team_players(payload: dict, league: str, team: str, squad: list[dict], stamp: str) -> tuple[int, int]:
    bucket = _bucket(payload, league)
    flat = list(bucket.get("players") or [])
    allowed = {_name_key(row.get("name")): row for row in squad if row.get("name")}
    kept = []
    purged = 0
    existing = {}
    for row in flat:
        if not isinstance(row, dict) or not _same_team(row.get("team"), team):
            kept.append(row)
            continue
        key = _name_key(row.get("player"))
        if key not in allowed:
            purged += 1
            continue
        current = dict(row)
        source = allowed[key]
        current["current_squad_member"] = True
        current["current_squad_checked_at"] = stamp
        current["current_squad_source"] = "API-Football · players/squads"
        current["player_id"] = current.get("player_id") or source.get("player_id")
        current["number"] = source.get("number")
        current["position"] = current.get("position") or source.get("position") or ""
        if source.get("photo"):
            profile = dict(current.get("profile") or {})
            profile.setdefault("photo", source.get("photo"))
            current["profile"] = profile
        kept.append(current)
        existing[key] = len(kept) - 1

    added = 0
    for key, source in allowed.items():
        if key in existing:
            continue
        kept.append({
            "player": source["name"],
            "team": team,
            "position": source.get("position") or "",
            "player_id": source.get("player_id"),
            "number": source.get("number"),
            "profile": {"photo": source.get("photo"), "age": source.get("age")},
            "goals": 0,
            "assists": 0,
            "shots": 0,
            "yc": 0,
            "min": 0,
            "source": "API-Football · current squad",
            "current_squad_member": True,
            "current_squad_checked_at": stamp,
            "current_squad_source": "API-Football · players/squads",
        })
        added += 1
    bucket["players"] = kept
    return purged, added


def _official_lineup(lineup: dict) -> bool:
    quality = lineup.get("quality") or {}
    provider = str(lineup.get("provider") or "").casefold()
    return bool(
        lineup.get("status") == "confirmado"
        and len(lineup.get("local") or []) == 11
        and len(lineup.get("visitante") or []) == 11
        and (quality.get("official") or lineup.get("source_quality") == "official" or "api-football" in provider)
    )


def _validate_lineup(match: dict, local_squad: list[dict], visitor_squad: list[dict], stamp: str) -> int:
    lineup = match.get("alineacion") or {}
    if not lineup or _official_lineup(lineup):
        return 0
    conflicts = {}
    for side, squad in (("local", local_squad), ("visitante", visitor_squad)):
        if len(squad) < 11:
            continue
        allowed = {_name_key(row.get("name")) for row in squad}
        bad = [name for name in (lineup.get(side) or []) if _name_key(name) not in allowed]
        if bad:
            conflicts[side] = bad
    if not conflicts:
        if local_squad or visitor_squad:
            lineup["current_squad_validated_at"] = stamp
            lineup["current_squad_conflicts"] = {}
            match["alineacion"] = lineup
        return 0

    lineup["status"] = "estimado"
    lineup["source_quality"] = "model_only"
    lineup["lineup_kind"] = "roster_conflict_withheld"
    lineup["current_squad_validated_at"] = stamp
    lineup["current_squad_conflicts"] = conflicts
    lineup["display_warning"] = (
        "XI oculto: contiene jugadores que no pertenecen a la plantilla registrada actual. "
        "Se volverá a construir con plantilla vigente, prensa reciente y continuidad de la temporada actual."
    )
    # Permite que el recolector de probables reintente inmediatamente en el mismo día.
    lineup.pop("critical_probable_checked_at", None)
    match["alineacion"] = lineup
    return sum(len(rows) for rows in conflicts.values())


def refresh_payload(payload: dict, now: datetime | None = None, football_client: ApiFootballClient | None = None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    stamp = now_local.isoformat()
    season = _season_start(now_local)
    matches = _target_matches(payload, now_local)
    client = football_client or ApiFootballClient()

    requested: dict[str, list[str]] = {}
    team_to_matches: dict[tuple[str, str], list[tuple[dict, str]]] = {}
    rosters: dict[tuple[str, str], list[dict]] = {}
    for match in matches:
        league = _league_key(match.get("league"))
        for side, team in (("local", match.get("home")), ("visitante", match.get("away"))):
            if not team:
                continue
            key = (league, str(team))
            cached = _cached_squad(payload, league, str(team), now_local)
            if cached:
                rosters[key] = cached
            else:
                requested.setdefault(league, []).append(str(team))
            team_to_matches.setdefault(key, []).append((match, side))

    fetched = 0
    api_calls_estimate = 0
    remaining_slots = MAX_NEW_TEAMS_PER_CYCLE
    for league, teams in requested.items():
        unique = list(dict.fromkeys(teams))[:remaining_slots]
        if not unique or remaining_slots <= 0:
            continue
        ids = _resolve_team_ids(client, league, unique, season)
        api_calls_estimate += int(bool(ids))
        for team in unique:
            team_id = ids.get(team)
            if not team_id:
                continue
            squad = _fetch_squad(client, team_id)
            api_calls_estimate += 1
            if len(squad) < 11:
                continue
            rosters[(league, team)] = squad
            fetched += 1
            remaining_slots -= 1
            if remaining_slots <= 0:
                break

    changed = False
    purged = added = conflicts = 0
    for (league, team), squad in rosters.items():
        p, a = _sync_team_players(payload, league, team, squad, stamp)
        purged += p
        added += a
        changed = changed or bool(p or a)

    for match in matches:
        league = _league_key(match.get("league"))
        local = rosters.get((league, str(match.get("home")))) or _cached_squad(payload, league, str(match.get("home")), now_local)
        visitor = rosters.get((league, str(match.get("away")))) or _cached_squad(payload, league, str(match.get("away")), now_local)
        before = json.dumps(match.get("current_squads") or {}, sort_keys=True, default=str)
        match["current_squads"] = {
            "source": "API-Football · players/squads",
            "season_context": season,
            "checked_at": stamp,
            "local": {"team": match.get("home"), "players": local} if local else None,
            "visitante": {"team": match.get("away"), "players": visitor} if visitor else None,
        }
        after = json.dumps(match.get("current_squads") or {}, sort_keys=True, default=str)
        changed = changed or before != after
        c = _validate_lineup(match, local, visitor, stamp)
        conflicts += c
        changed = changed or bool(c)

    health = dict(payload.get("source_health") or {})
    health["current_squads"] = {
        "checked_at": stamp,
        "source": "API-Football · players/squads",
        "season_context": season,
        "matches": len(matches),
        "teams_cached_or_fetched": len(rosters),
        "teams_fetched": fetched,
        "stale_players_purged": purged,
        "players_added": added,
        "lineup_conflicts": conflicts,
        "api_calls_estimate": api_calls_estimate,
    }
    payload["source_health"] = health
    return changed, health["current_squads"]


def run(path=OUTPUT, now: datetime | None = None):
    previous = load_feed(path)
    if not previous:
        return False, {"error": "feed_missing"}
    candidate = deepcopy(previous)
    changed, stats = refresh_payload(candidate, now=now)
    if not changed:
        return False, stats
    candidate["generated_at"] = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID).isoformat()
    ok, report = write_feed_safely(path, candidate, previous=previous)
    stats["feed_valid"] = bool(ok)
    stats["feed_issues"] = report.get("issues") or []
    return ok, stats


def main() -> int:
    ok, stats = run()
    print(json.dumps({"written": ok, **stats}, ensure_ascii=False, sort_keys=True))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
