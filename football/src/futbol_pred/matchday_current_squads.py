"""Plantillas actuales como fuente autoritativa del feed.

La plantilla de un club NO se deriva de ``previous.players``. Para LaLiga y
Segunda se recorre toda la temporada actual y se sincroniza incrementalmente
contra API-Football ``/players/squads`` (plantilla registrada actual, sin
parámetro season). Champions se consulta para los equipos con partido próximo.

Principios:
- equipos con partido próximo siempre tienen prioridad;
- LaLiga/Segunda completas se sanea en segundo plano;
- una plantilla real conserva la hora REAL de consulta: reutilizarla no renueva
  artificialmente su TTL;
- ids de club se cachean 24h para no pagar ``/teams`` en cada ciclo;
- ningún XI no oficial puede publicar un jugador fuera de la plantilla actual;
- se reserva cuota API-Football para XI oficial/bajas de la ventana crítica.
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
ROSTER_TTL_HOURS = 24
TEAM_ID_TTL_HOURS = 24
WINDOW_PAST_HOURS = 3
WINDOW_FUTURE_HOURS = 36
MAX_NEW_TEAMS_PER_CYCLE = 6
API_RESERVE = 30
GLOBAL_LEAGUES = {"laliga", "segunda"}


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
    return sorted(out, key=lambda row: _parse(row.get("kickoff")) or now_local)


def _team_order(payload: dict, now_local: datetime) -> list[tuple[str, str]]:
    """Próximos primero; después todos los clubes de LaLiga/Segunda actuales."""
    out: list[tuple[str, str]] = []
    seen = set()

    def add(league: str, team) -> None:
        team = str(team or "").strip()
        key = (league, _key(team))
        if team and key not in seen:
            seen.add(key)
            out.append((league, team))

    for match in _target_matches(payload, now_local):
        league = _league_key(match.get("league"))
        add(league, match.get("home"))
        add(league, match.get("away"))

    season_matches = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        league = _league_key(match.get("league"))
        if league not in GLOBAL_LEAGUES:
            continue
        kickoff = _parse(match.get("kickoff"))
        season_matches.append((kickoff or now_local, league, match))
    season_matches.sort(key=lambda row: row[0])
    for _, league, match in season_matches:
        add(league, match.get("home"))
        add(league, match.get("away"))
    return out


def _bucket(payload: dict, league: str) -> dict:
    labels = {"laliga": "LaLiga", "segunda": "LaLiga Hypermotion", "champions": "Champions League"}
    players = payload.setdefault("players", {})
    return players.setdefault(league, {"label": labels.get(league, league), "rankings": {}, "players": []})


def _cached_squad(payload: dict, league: str, team: str, now_local: datetime) -> tuple[list[dict], str | None]:
    rows = _bucket(payload, league).get("players") or []
    squad = []
    stamps = []
    for row in rows:
        if not isinstance(row, dict) or not _same_team(row.get("team"), team):
            continue
        if not row.get("current_squad_member"):
            continue
        stamp = _parse(row.get("current_squad_checked_at"))
        if stamp is None:
            continue
        stamps.append(stamp)
        squad.append({
            "name": row.get("player"),
            "position": row.get("position") or row.get("api_position") or "",
            "player_id": row.get("player_id"),
            "number": row.get("number"),
            "photo": (row.get("profile") or {}).get("photo") if isinstance(row.get("profile"), dict) else row.get("photo"),
        })
    if len(squad) >= 11 and stamps:
        oldest = min(stamps)
        if (now_local - oldest).total_seconds() / 3600.0 <= ROSTER_TTL_HOURS:
            return [row for row in squad if row.get("name")], oldest.isoformat()
    return [], None


def _remaining(payload: dict) -> int | None:
    try:
        return int(((payload.get("source_health") or {}).get("api_football") or {}).get("daily_remaining"))
    except (TypeError, ValueError):
        return None


def _load_team_id_cache(payload: dict, now_local: datetime, season: int) -> dict[str, dict[str, int]]:
    block = ((payload.get("source_health") or {}).get("current_squads") or {})
    if block.get("season_context") != season:
        return {}
    age = _age_hours(block.get("team_ids_checked_at"), now_local)
    if age is None or age > TEAM_ID_TTL_HOURS:
        return {}
    raw = block.get("team_ids") or {}
    out = {}
    for league, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        cleaned = {}
        for name, team_id in mapping.items():
            try:
                cleaned[str(name)] = int(team_id)
            except (TypeError, ValueError):
                pass
        if cleaned:
            out[league] = cleaned
    return out


def _fetch_league_team_ids(client: ApiFootballClient, league: str, season: int) -> dict[str, int]:
    if client.offline:
        return {}
    try:
        rows = client._get("teams", {"league": LEAGUES[league], "season": season}).get("response") or []
    except Exception:
        return {}
    out = {}
    for row in rows:
        team = row.get("team") or {}
        if team.get("id") and team.get("name"):
            out[str(team["name"])] = int(team["id"])
    return out


def _resolve_team_id(team: str, candidates: dict[str, int]) -> int | None:
    wanted = _key(team)
    for name, team_id in candidates.items():
        if _key(name) == wanted:
            return team_id
    best = None
    for name, team_id in candidates.items():
        score = SequenceMatcher(None, wanted, _key(name)).ratio()
        if best is None or score > best[0]:
            best = (score, team_id)
    return best[1] if best and best[0] >= 0.68 else None


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


def _sync_team_players(payload: dict, league: str, team: str, squad: list[dict], checked_at: str, season: int) -> tuple[int, int, int]:
    bucket = _bucket(payload, league)
    flat = list(bucket.get("players") or [])
    allowed = {_name_key(row.get("name")): row for row in squad if row.get("name")}
    kept = []
    purged = added = updated = 0
    existing = set()
    for row in flat:
        if not isinstance(row, dict) or not _same_team(row.get("team"), team):
            kept.append(row)
            continue
        key = _name_key(row.get("player"))
        if key not in allowed:
            purged += 1
            continue
        source = allowed[key]
        current = dict(row)
        current["current_squad_member"] = True
        current["current_squad_checked_at"] = checked_at
        current["current_squad_source"] = "API-Football · players/squads"
        current["current_squad_season_context"] = season
        current["player_id"] = current.get("player_id") or source.get("player_id")
        current["number"] = source.get("number")
        current["position"] = source.get("position") or current.get("position") or ""
        if source.get("photo"):
            profile = dict(current.get("profile") or {})
            profile["photo"] = source.get("photo")
            if source.get("age") is not None:
                profile["age"] = source.get("age")
            current["profile"] = profile
        if current != row:
            updated += 1
        kept.append(current)
        existing.add(key)

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
            "goals": 0, "assists": 0, "shots": 0, "yc": 0, "min": 0,
            "source": "API-Football · current squad",
            "current_squad_member": True,
            "current_squad_checked_at": checked_at,
            "current_squad_source": "API-Football · players/squads",
            "current_squad_season_context": season,
        })
        added += 1
    bucket["players"] = kept
    return purged, added, updated


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
        return 0
    lineup["status"] = "estimado"
    lineup["source_quality"] = "model_only"
    lineup["lineup_kind"] = "roster_conflict_withheld"
    lineup["current_squad_validated_at"] = stamp
    lineup["current_squad_conflicts"] = conflicts
    lineup["display_warning"] = (
        "XI oculto: contiene jugadores que no pertenecen a la plantilla registrada actual. "
        "Se reconstruirá con plantilla vigente, prensa reciente y continuidad de 2026/27."
    )
    lineup.pop("critical_probable_checked_at", None)
    match["alineacion"] = lineup
    return sum(len(rows) for rows in conflicts.values())


def refresh_payload(payload: dict, now: datetime | None = None, football_client: ApiFootballClient | None = None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    stamp = now_local.isoformat()
    season = _season_start(now_local)
    target_matches = _target_matches(payload, now_local)
    client = football_client or ApiFootballClient()
    order = _team_order(payload, now_local)

    health_root = dict(payload.get("source_health") or {})
    previous_health = dict(health_root.get("current_squads") or {})
    team_ids = _load_team_id_cache(payload, now_local, season)
    ids_changed = False

    rosters: dict[tuple[str, str], tuple[list[dict], str]] = {}
    requested: list[tuple[str, str]] = []
    for league, team in order:
        squad, checked_at = _cached_squad(payload, league, team, now_local)
        if squad and checked_at:
            rosters[(league, team)] = (squad, checked_at)
        else:
            requested.append((league, team))

    remaining = _remaining(payload)
    slots = MAX_NEW_TEAMS_PER_CYCLE
    if remaining is not None:
        slots = min(slots, max(0, remaining - API_RESERVE))

    fetched = 0
    api_calls_estimate = 0
    for league, team in requested:
        if fetched >= slots:
            break
        candidates = team_ids.get(league)
        if not candidates:
            if remaining is not None and remaining - api_calls_estimate <= API_RESERVE + 1:
                break
            candidates = _fetch_league_team_ids(client, league, season)
            api_calls_estimate += 1
            if not candidates:
                continue
            team_ids[league] = candidates
            ids_changed = True
        team_id = _resolve_team_id(team, candidates)
        if not team_id:
            continue
        if remaining is not None and remaining - api_calls_estimate <= API_RESERVE:
            break
        squad = _fetch_squad(client, team_id)
        api_calls_estimate += 1
        if len(squad) < 11:
            continue
        rosters[(league, team)] = (squad, stamp)
        fetched += 1

    changed = ids_changed
    purged = added = updated = conflicts = 0
    for (league, team), (squad, checked_at) in rosters.items():
        p, a, u = _sync_team_players(payload, league, team, squad, checked_at, season)
        purged += p
        added += a
        updated += u
        changed = changed or bool(p or a or u)

    for match in target_matches:
        league = _league_key(match.get("league"))
        local_pair = rosters.get((league, str(match.get("home"))))
        visitor_pair = rosters.get((league, str(match.get("away"))))
        local, local_at = local_pair or _cached_squad(payload, league, str(match.get("home")), now_local)
        visitor, visitor_at = visitor_pair or _cached_squad(payload, league, str(match.get("away")), now_local)
        block = {
            "source": "API-Football · players/squads",
            "season_context": season,
            "local": {"team": match.get("home"), "checked_at": local_at, "players": local} if local else None,
            "visitante": {"team": match.get("away"), "checked_at": visitor_at, "players": visitor} if visitor else None,
        }
        if match.get("current_squads") != block:
            match["current_squads"] = block
            changed = True
        c = _validate_lineup(match, local, visitor, stamp)
        conflicts += c
        changed = changed or bool(c)

    health = {
        "checked_at": stamp,
        "source": "API-Football · players/squads",
        "season_context": season,
        "scope": "LaLiga+Segunda completas; Champions bajo demanda",
        "roster_ttl_hours": ROSTER_TTL_HOURS,
        "target_matches": len(target_matches),
        "teams_total_target": len(order),
        "teams_cached_or_fetched": len(rosters),
        "teams_fetched": fetched,
        "stale_players_purged": purged,
        "players_added": added,
        "players_metadata_updated": updated,
        "lineup_conflicts": conflicts,
        "api_calls_estimate": api_calls_estimate,
        "quota_remaining_before": remaining,
        "quota_reserve": API_RESERVE,
        "team_ids": team_ids,
        "team_ids_checked_at": stamp if ids_changed or not previous_health.get("team_ids_checked_at") else previous_health.get("team_ids_checked_at"),
    }
    health_root["current_squads"] = health
    payload["source_health"] = health_root
    if changed:
        payload["generated_at"] = stamp
    return changed, health


def run(path=OUTPUT, now: datetime | None = None):
    previous = load_feed(path)
    if not previous:
        return False, {"error": "feed_missing"}
    candidate = deepcopy(previous)
    changed, stats = refresh_payload(candidate, now=now)
    if not changed:
        return False, stats
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
