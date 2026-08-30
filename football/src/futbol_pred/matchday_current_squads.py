"""Plantillas actuales como fuente autoritativa del feed.

La plantilla de un club NO se deriva de ``previous.players``. LaLiga y Segunda
se sincronizan de una vez desde football-data.org ``competitions/{code}/teams``
(que incluye ``squad`` de la temporada solicitada). API-Football queda como
fallback para equipos próximos si esa fuente no devuelve plantilla y como
contraste del XI oficial cerca del kickoff.

La reutilización de una plantilla cacheada conserva la hora REAL de la consulta:
no se rejuvenece una foto vieja solo por leerla de nuevo.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import unicodedata

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, _aware, _parse
from .ingest.api_football import ApiFootballClient
from .ingest.football_data import FootballDataClient
from .ingest.lineups_ai import _formation, _probable_positions, _probable_xi

OUTPUT = DATA_DIR / "dashboard.json"
ROSTER_TTL_HOURS = 24
WINDOW_PAST_HOURS = 3
WINDOW_FUTURE_HOURS = 36
GLOBAL_LEAGUES = {"laliga", "segunda"}
API_FALLBACK_MAX_TEAMS = 4
API_RESERVE = 30


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


def _strip_accents(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _name_key(value: str | None) -> str:
    # Insensible a acentos: "Tchouaméni" y "Tchouameni" deben cotejar igual.
    return "".join(ch for ch in _strip_accents(value).casefold() if ch.isalnum())


def _name_tokens(value: str | None) -> set[str]:
    plain = re.sub(r"[^a-z0-9 ]", " ", _strip_accents(value).casefold())
    return {tok for tok in plain.split() if len(tok) >= 3}


def _roster_lookup(squad: list[dict]) -> tuple[dict[str, str], list[tuple[set[str], str]]]:
    exact: dict[str, str] = {}
    tokens: list[tuple[set[str], str]] = []
    for row in squad or []:
        name = row.get("name") if isinstance(row, dict) else row
        if not name:
            continue
        exact.setdefault(_name_key(name), name)
        tokens.append((_name_tokens(name), name))
    return exact, tokens


def _resolve_squad_name(name: str, exact: dict[str, str], tokens: list[tuple[set[str], str]]) -> str | None:
    """Nombre canónico de plantilla que corresponde a ``name``, o None.

    Tolera acentos y nombres parciales frecuentes (p.ej. "Rodrygo Goes" ↔
    "Rodrygo") sin arriesgar falsos positivos: exige subconjunto de tokens o al
    menos dos tokens compartidos.
    """
    key = _name_key(name)
    if key in exact:
        return exact[key]
    wanted = _name_tokens(name)
    if not wanted:
        return None
    for tset, canonical in tokens:
        if tset and (wanted <= tset or tset <= wanted):
            return canonical
    for tset, canonical in tokens:
        if len(wanted & tset) >= 2:
            return canonical
    return None


def _same_team(left: str | None, right: str | None) -> bool:
    a, b = _key(left), _key(right)
    return bool(a and b and (a == b or a in b or b in a))


def _age_hours(value, now_local: datetime) -> float | None:
    stamp = _parse(value)
    if stamp is None:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 3600.0)


def _bucket(payload: dict, league: str) -> dict:
    labels = {"laliga": "LaLiga", "segunda": "LaLiga Hypermotion", "champions": "Champions League"}
    return payload.setdefault("players", {}).setdefault(
        league, {"label": labels.get(league, league), "rankings": {}, "players": []}
    )


def _cached_squad(payload: dict, league: str, team: str, now_local: datetime) -> tuple[list[dict], str | None]:
    rows = _bucket(payload, league).get("players") or []
    squad, stamps = [], []
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


def _league_teams(payload: dict, league: str) -> list[str]:
    out, seen = [], set()
    for match in payload.get("matches") or []:
        if _league_key(match.get("league")) != league:
            continue
        for team in (match.get("home"), match.get("away")):
            team = str(team or "").strip()
            key = _key(team)
            if team and key not in seen:
                seen.add(key)
                out.append(team)
    return out


def _find_named_squad(squads: dict[str, list[dict]], wanted: str) -> tuple[str | None, list[dict]]:
    for name, squad in squads.items():
        if _same_team(name, wanted):
            return name, squad
    return None, []


def _sync_team_players(
    payload: dict,
    league: str,
    team: str,
    squad: list[dict],
    checked_at: str,
    season: int,
    source_label: str,
) -> tuple[int, int, int]:
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
        raw = allowed[key]
        current = dict(row)
        current.update({
            "current_squad_member": True,
            "current_squad_checked_at": checked_at,
            "current_squad_source": source_label,
            "current_squad_season_context": season,
        })
        if raw.get("position"):
            current["position"] = raw.get("position")
        if raw.get("player_id") is not None:
            current["player_id"] = raw.get("player_id")
        if raw.get("number") is not None:
            current["number"] = raw.get("number")
        if raw.get("photo"):
            profile = dict(current.get("profile") or {})
            profile["photo"] = raw.get("photo")
            if raw.get("age") is not None:
                profile["age"] = raw.get("age")
            current["profile"] = profile
        if current != row:
            updated += 1
        kept.append(current)
        existing.add(key)

    for key, raw in allowed.items():
        if key in existing:
            continue
        kept.append({
            "player": raw["name"], "team": team,
            "position": raw.get("position") or "",
            "player_id": raw.get("player_id"), "number": raw.get("number"),
            "profile": {"photo": raw.get("photo"), "age": raw.get("age")},
            "goals": 0, "assists": 0, "shots": 0, "yc": 0, "min": 0,
            "source": source_label,
            "current_squad_member": True,
            "current_squad_checked_at": checked_at,
            "current_squad_source": source_label,
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


def _repair_side(lineup: dict, side: str, squad: list[dict]) -> tuple[list[str] | None, list[str] | None, list[str]]:
    """Reconstruye el XI de un lado sobre la plantilla real.

    Conserva (con su nombre canónico) los jugadores del XI que pertenecen a la
    plantilla y sustituye a los que no por titulares probables de la plantilla
    vigente. Devuelve ``(xi, posiciones, no_resueltos)``; ``xi`` es ``None`` si la
    plantilla no basta para completar once nombres.
    """
    exact, tokens = _roster_lookup(squad)
    unresolved: list[str] = []
    kept: list[str] = []
    seen: set[str] = set()
    for name in (lineup.get(side) or []):
        if not name:
            continue
        canonical = _resolve_squad_name(name, exact, tokens)
        if canonical is None:
            unresolved.append(name)
            continue
        key = _name_key(canonical)
        if key in seen:
            continue
        seen.add(key)
        kept.append(canonical)
    if len(kept) < 11:
        for name in _probable_xi(squad) or []:
            if len(kept) >= 11:
                break
            key = _name_key(name)
            if key not in seen:
                seen.add(key)
                kept.append(name)
    if len(kept) < 11:
        return None, None, unresolved
    xi = kept[:11]
    return xi, _probable_positions(squad, xi), unresolved


def _validate_lineup(match: dict, local_squad: list[dict], visitor_squad: list[dict], stamp: str) -> int:
    lineup = match.get("alineacion") or {}
    if not lineup or _official_lineup(lineup):
        return 0
    conflicts: dict[str, list[str]] = {}
    repaired_any = False
    withheld = False
    for side, squad, pos_key in (
        ("local", local_squad, "posiciones_local"),
        ("visitante", visitor_squad, "posiciones_visitante"),
    ):
        if len(squad) < 11:
            continue
        exact, tokens = _roster_lookup(squad)
        bad = [name for name in (lineup.get(side) or []) if _resolve_squad_name(name, exact, tokens) is None]
        if not bad:
            continue
        conflicts[side] = bad
        xi, positions, _ = _repair_side(lineup, side, squad)
        if not xi:
            withheld = True
            continue
        lineup[side] = xi
        lineup[pos_key] = positions
        repaired_any = True

    if not conflicts:
        return 0

    if withheld and not repaired_any:
        # No hubo plantilla suficiente para reconstruir: se oculta como antes.
        lineup.update({
            "status": "estimado",
            "source_quality": "model_only",
            "lineup_kind": "roster_conflict_withheld",
            "current_squad_validated_at": stamp,
            "current_squad_conflicts": conflicts,
            "display_warning": (
                "XI oculto: contiene jugadores que no pertenecen a la plantilla registrada actual. "
                "Se reconstruirá con plantilla vigente, prensa reciente y continuidad de 2026/27."
            ),
        })
        lineup.pop("critical_probable_checked_at", None)
    else:
        # Reconstruido desde la plantilla vigente: se muestra con aviso honesto.
        lineup.update({
            "status": "estimado",
            "source_quality": "roster_grounded",
            "lineup_kind": "roster_reconstructed",
            "positions_inferred": True,
            "formacion_local": _formation(lineup.get("posiciones_local")),
            "formacion_visitante": _formation(lineup.get("posiciones_visitante")),
            "current_squad_validated_at": stamp,
            "current_squad_conflicts": conflicts,
            "display_warning": (
                "XI probable reconstruido con la plantilla vigente: se sustituyeron "
                "jugadores que ya no constan en el club por titulares probables de la plantilla actual."
            ),
        })
        lineup.pop("display_withheld", None)
    match["alineacion"] = lineup
    return sum(len(rows) for rows in conflicts.values())


def _remaining(payload: dict) -> int | None:
    try:
        return int(((payload.get("source_health") or {}).get("api_football") or {}).get("daily_remaining"))
    except (TypeError, ValueError):
        return None


def _api_fallback_squad(client, team: str) -> list[dict]:
    if getattr(client, "offline", False):
        return []
    if hasattr(client, "get_squad"):
        try:
            return client.get_squad(team) or []
        except Exception:
            return []
    # Compatibilidad con fakes de tests.
    try:
        rows = client._get("teams", {"search": team}).get("response") or []
        chosen = next((row for row in rows if _same_team((row.get("team") or {}).get("name"), team)), rows[0] if rows else None)
        team_id = ((chosen or {}).get("team") or {}).get("id")
        if not team_id:
            return []
        response = client._get("players/squads", {"team": team_id}).get("response") or []
        return (response[0].get("players") or []) if response else []
    except Exception:
        return []


def refresh_payload(
    payload: dict,
    now: datetime | None = None,
    football_client: ApiFootballClient | None = None,
    football_data_client: FootballDataClient | None = None,
) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    stamp = now_local.isoformat()
    season = _season_start(now_local)
    targets = _target_matches(payload, now_local)
    api = football_client or ApiFootballClient()
    fd = football_data_client or FootballDataClient()

    changed = False
    purged = added = updated = conflicts = 0
    fd_refreshed = []
    api_fetched = 0
    rosters: dict[tuple[str, str], tuple[list[dict], str, str]] = {}

    # 1) LaLiga y Segunda completas: una petición por competición cuando falta
    #    alguna plantilla o ha caducado la foto de 24h.
    for league in ("laliga", "segunda"):
        teams = _league_teams(payload, league)
        stale = []
        for team in teams:
            squad, checked = _cached_squad(payload, league, team, now_local)
            if squad and checked:
                rosters[(league, team)] = (squad, checked, "cache current squad")
            else:
                stale.append(team)
        if not stale or getattr(fd, "offline", False):
            continue
        try:
            meta = fd.get_team_meta(league, season)
        except Exception:
            meta = {}
        if not meta:
            continue
        fd_refreshed.append(league)
        for team in teams:
            api_name, squad = _find_named_squad(
                {name: info.get("squad") or [] for name, info in meta.items()}, team
            )
            if len(squad) < 11:
                continue
            source = "football-data.org · current season squad"
            p, a, u = _sync_team_players(payload, league, team, squad, stamp, season, source)
            purged += p; added += a; updated += u
            changed = changed or bool(p or a or u)
            rosters[(league, team)] = (squad, stamp, source)

    # 2) Equipos próximos aún sin roster: fallback API-Football, con reserva de
    #    cuota para bajas/XI oficial.
    remaining = _remaining(payload)
    fallback_budget = API_FALLBACK_MAX_TEAMS
    if remaining is not None:
        fallback_budget = min(fallback_budget, max(0, (remaining - API_RESERVE) // 2))
    for match in targets:
        league = _league_key(match.get("league"))
        for team in (str(match.get("home") or ""), str(match.get("away") or "")):
            if not team or (league, team) in rosters or api_fetched >= fallback_budget:
                continue
            squad = _api_fallback_squad(api, team)
            if len(squad) < 11:
                continue
            source = "API-Football · players/squads"
            p, a, u = _sync_team_players(payload, league, team, squad, stamp, season, source)
            purged += p; added += a; updated += u
            changed = changed or bool(p or a or u)
            rosters[(league, team)] = (squad, stamp, source)
            api_fetched += 1

    # 3) Estado por partido + barrera de coherencia de XI.
    for match in targets:
        league = _league_key(match.get("league"))
        local_pair = rosters.get((league, str(match.get("home"))))
        visitor_pair = rosters.get((league, str(match.get("away"))))
        if local_pair:
            local, local_at, local_source = local_pair
        else:
            local, local_at = _cached_squad(payload, league, str(match.get("home")), now_local)
            local_source = "cache current squad"
        if visitor_pair:
            visitor, visitor_at, visitor_source = visitor_pair
        else:
            visitor, visitor_at = _cached_squad(payload, league, str(match.get("away")), now_local)
            visitor_source = "cache current squad"
        block = {
            "season_context": season,
            "local": {"team": match.get("home"), "source": local_source, "checked_at": local_at, "players": local} if local else None,
            "visitante": {"team": match.get("away"), "source": visitor_source, "checked_at": visitor_at, "players": visitor} if visitor else None,
        }
        if match.get("current_squads") != block:
            match["current_squads"] = block
            changed = True
        c = _validate_lineup(match, local, visitor, stamp)
        conflicts += c
        changed = changed or bool(c)

    health_root = dict(payload.get("source_health") or {})
    health = {
        "checked_at": stamp,
        "season_context": season,
        "scope": "LaLiga+Segunda completas; Champions/próximos por fallback",
        "roster_ttl_hours": ROSTER_TTL_HOURS,
        "target_matches": len(targets),
        "football_data_leagues_refreshed": fd_refreshed,
        # Contrato histórico de observabilidad: consumidores/tests antiguos usan
        # teams_fetched para saber cuántos equipos requirieron llamadas de fallback.
        # Se conserva como alias explícito del contador más preciso actual.
        "teams_fetched": api_fetched,
        "api_fallback_teams_fetched": api_fetched,
        "stale_players_purged": purged,
        "players_added": added,
        "players_metadata_updated": updated,
        "lineup_conflicts": conflicts,
        "api_quota_remaining_before": remaining,
        "api_quota_reserve": API_RESERVE,
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
