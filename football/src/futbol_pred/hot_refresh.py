"""Refresco ligero intradía para Fútbol Edge.

No reentrena modelos ni llama a IA. Su objetivo es reducir la latencia de la
información que sí cambia cerca del partido: estado/marcador, meteorología,
bajas oficiales y XI oficial. El pipeline completo sigue siendo la autoridad
para recalcular probabilidades, props, impactos y snapshots auditables.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

from .config import DATA_DIR
from .context import WeatherClient, venue_for
from .feed_quality import load_feed, write_feed_safely
from .ingest.api_football import ApiFootballClient

MADRID = ZoneInfo("Europe/Madrid")
OUTPUT = Path(DATA_DIR) / "dashboard.json"
FINISHED = {"FT", "AET", "PEN", "AWD", "FINISHED", "AWARDED"}
LINEUP_TARGETS_MIN = (70, 60, 50, 40, 30, 20)
ABSENCE_TARGETS_MIN = (360, 120, 60)
POLL_TOLERANCE_MIN = 6


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse(value) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(str(value))).astimezone(MADRID)
    except (TypeError, ValueError):
        return None


def _key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"\b(fc|cf|cd|ud|club|deportivo|real)\b|[^a-z0-9]", "", text)


def _same_team(left: str | None, right: str | None) -> bool:
    a, b = _key(left), _key(right)
    return bool(a and b and (a == b or a in b or b in a))


def _near_target(minutes_to_kickoff: float, targets: tuple[int, ...]) -> bool:
    return any(abs(minutes_to_kickoff - target) <= POLL_TOLERANCE_MIN for target in targets)


def _without_refresh_stamp(value: dict | None) -> dict:
    out = dict(value or {})
    out.pop("source_updated_at", None)
    return out


def _availability_core(rows) -> list[dict]:
    out = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        row.pop("source_updated_at", None)
        out.append(row)
    return out


def _record_check(match: dict, key: str, now_local: datetime, result: str | None = None) -> bool:
    """Registra una comprobación real, aunque la fuente no haya cambiado.

    ``updatedAt`` sigue significando último cambio de contenido. Esta metadata
    separada permite a la UI mostrar cuándo se consultó de verdad cada fuente.
    """
    checks = dict(match.get("operational_checks") or {})
    stamp_key = f"{key}_checked_at"
    stamp = now_local.isoformat()
    changed = checks.get(stamp_key) != stamp
    checks[stamp_key] = stamp
    if result is not None:
        result_key = f"{key}_check_result"
        changed = changed or checks.get(result_key) != result
        checks[result_key] = result
    match["operational_checks"] = checks
    return changed


def _official_by_side(official: list[dict], match: dict) -> dict[str, dict]:
    sides = {}
    for team in official or []:
        name = team.get("team")
        if _same_team(name, match.get("home")):
            sides["local"] = team
        elif _same_team(name, match.get("away")):
            sides["visitante"] = team
    return sides


def _filter_props(rows, names: list[str]) -> list[dict]:
    allowed = {_key(name) for name in names}
    return [
        row for row in (rows or [])
        if isinstance(row, dict) and _key(row.get("jugador")) in allowed
    ]


def _merge_official_lineup(match: dict, official: list[dict], fixture_id: int,
                           now_local: datetime, minutes_to_kickoff: float) -> bool:
    sides = _official_by_side(official, match)
    if set(sides) != {"local", "visitante"}:
        return False
    local_rows = sides["local"].get("starters") or []
    away_rows = sides["visitante"].get("starters") or []
    if len(local_rows) != 11 or len(away_rows) != 11:
        return False

    local = [row.get("name") for row in local_rows]
    away = [row.get("name") for row in away_rows]
    if not all(local) or not all(away):
        return False
    old = dict(match.get("alineacion") or {})
    if (
        old.get("status") == "confirmado"
        and old.get("local") == local
        and old.get("visitante") == away
    ):
        return False

    positions_local = [row.get("position") or "" for row in local_rows]
    positions_away = [row.get("position") or "" for row in away_rows]
    key_local = _filter_props(old.get("clave_local"), local)
    key_away = _filter_props(old.get("clave_visitante"), away)
    poll_window = "T-60" if minutes_to_kickoff >= 45 else "T-30"
    stamp = now_local.isoformat()
    attempts = dict(old.get("official_poll_windows") or {})
    attempts[poll_window] = stamp
    match["alineacion"] = {
        **old,
        "local": local,
        "visitante": away,
        "posiciones_local": positions_local,
        "posiciones_visitante": positions_away,
        "formacion_local": sides["local"].get("formation") or old.get("formacion_local"),
        "formacion_visitante": sides["visitante"].get("formation") or old.get("formacion_visitante"),
        "positions_inferred": False,
        "clave_local": key_local,
        "clave_visitante": key_away,
        "best_props": [
            row for row in (old.get("best_props") or [])
            if _key(row.get("jugador")) in ({_key(name) for name in local} | {_key(name) for name in away})
        ],
        "status": "confirmado",
        "phase": "final",
        "lineup_kind": "official",
        "provider": "API-Football",
        "model": "alineación oficial",
        "fuente": f"API-Football · hot refresh · {poll_window}",
        "official_poll_window": poll_window,
        "official_poll_windows": attempts,
        "official_poll_at": stamp,
        "official_fixture_id": fixture_id,
        "source_updated_at": stamp,
        "generated_at": stamp,
        "ts": stamp,
        "numeric_props_source": old.get("numeric_props_source") if key_local or key_away else "pending_real_data",
        "quality": {
            **(old.get("quality") or {}),
            "complete": True,
            "lineup_players": 22,
            "positions_players": 22,
            "props_players": len(key_local) + len(key_away),
            "score": 1.0,
            "official": True,
            "official_poll_window": poll_window,
            "hot_refresh": True,
        },
    }
    return True


def _merge_absences(match: dict, absences: list[dict], now_local: datetime) -> bool:
    lineup = match.get("alineacion")
    # Crear un bloque de alineación vacío haría fallar el contrato de calidad.
    if not isinstance(lineup, dict):
        return False
    changed = False
    stamp = now_local.isoformat()
    for side, team in (("local", match.get("home")), ("visitante", match.get("away"))):
        rows = [
            {**item, "source_updated_at": stamp}
            for item in (absences or [])
            if isinstance(item, dict) and _same_team(item.get("team"), team)
        ]
        field = f"disponibilidad_{side}"
        old_rows = lineup.get(field)
        # Si el endpoint devuelve 0 bajas para un lado, limpiamos una baja antigua
        # si existía. No fabricamos un campo vacío si nunca hubo datos previos.
        if not rows and old_rows is None:
            continue
        if _availability_core(old_rows) == _availability_core(rows):
            continue
        lineup[field] = rows
        lineup[f"bajas_{side}"] = [
            f"{row.get('jugador')} ({row.get('detalle') or row.get('estado') or 'baja'})"
            for row in rows if row.get("jugador")
        ]
        changed = True
    return changed


def _refresh_weather(match: dict, now_local: datetime, client: WeatherClient) -> bool:
    kickoff = _parse(match.get("kickoff"))
    if not kickoff or kickoff.date() != now_local.date() or match.get("finished"):
        return False
    hours = (kickoff - now_local).total_seconds() / 3600
    if not -1 <= hours <= 8:
        return False
    venue = venue_for(match.get("home", ""))
    if not venue:
        return False

    forecast = client.forecast(venue, kickoff)
    check_changed = _record_check(
        match, "weather", now_local, "ok" if forecast else "unavailable"
    )
    if not forecast:
        return check_changed

    match["venue"] = venue["name"]
    match["venue_meta"] = venue
    if _without_refresh_stamp(match.get("weather")) == _without_refresh_stamp(forecast):
        return check_changed
    forecast["source_updated_at"] = now_local.isoformat()
    match["weather"] = forecast
    match["updatedAt"] = now_local.isoformat()
    return True


def _refresh_api_match(match: dict, now_local: datetime, client: ApiFootballClient) -> tuple[bool, dict]:
    kickoff = _parse(match.get("kickoff"))
    if not kickoff or kickoff.date() != now_local.date():
        return False, {"fixture": False, "lineup": False, "absences": False}
    minutes = (kickoff - now_local).total_seconds() / 60
    wants_live = -180 <= minutes <= 180
    wants_lineup = (
        not match.get("finished")
        and (match.get("alineacion") or {}).get("status") != "confirmado"
        and _near_target(minutes, LINEUP_TARGETS_MIN)
    )
    wants_absences = not match.get("finished") and _near_target(minutes, ABSENCE_TARGETS_MIN)
    if not (wants_live or wants_lineup or wants_absences):
        return False, {"fixture": False, "lineup": False, "absences": False}

    raw = client.find_fixture(match.get("home", ""), match.get("away", ""), kickoff)
    fixture = (raw or {}).get("fixture") or {}
    fixture_id = fixture.get("id")
    changed = _record_check(
        match, "fixture", now_local, "ok" if fixture_id else "not_found"
    )
    touched = {"fixture": False, "lineup": False, "absences": False}
    if not fixture_id:
        return changed, touched

    status = str((fixture.get("status") or {}).get("short") or match.get("status") or "")
    goals = (raw or {}).get("goals") or {}
    home_goals, away_goals = goals.get("home"), goals.get("away")
    if status and status != match.get("status"):
        match["status"] = status
        changed = touched["fixture"] = True
    if home_goals is not None and away_goals is not None:
        score = [home_goals, away_goals]
        if match.get("live_score") != score:
            match["live_score"] = score
            changed = touched["fixture"] = True
    if status.upper() in FINISHED and home_goals is not None and away_goals is not None:
        score = [home_goals, away_goals]
        if not match.get("finished") or match.get("result") != score:
            match["finished"] = True
            match["result"] = score
            match["engine"] = "resultado-real"
            changed = touched["fixture"] = True

    if wants_absences:
        absences = client.get_absences(int(fixture_id))
        changed = _record_check(
            match, "absences", now_local, "ok" if absences is not None else "unavailable"
        ) or changed
        if absences is not None and _merge_absences(match, absences, now_local):
            changed = touched["absences"] = True

    if wants_lineup:
        official = client.get_official_lineup(int(fixture_id))
        published = bool(_official_by_side(official or [], match))
        changed = _record_check(
            match, "lineup", now_local, "published" if published else "not_published"
        ) or changed
        if _merge_official_lineup(match, official or [], int(fixture_id), now_local, minutes):
            changed = touched["lineup"] = True

    if any(touched.values()):
        match["updatedAt"] = now_local.isoformat()
    return changed, touched


def refresh_payload(payload: dict, now: datetime | None = None,
                    weather_client: WeatherClient | None = None,
                    football_client: ApiFootballClient | None = None) -> tuple[bool, dict]:
    """Muta un feed válido con datos rápidos del día y devuelve contadores."""
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    weather = weather_client or WeatherClient()
    football = football_client or ApiFootballClient()
    stats = {"weather": 0, "fixture": 0, "lineup": 0, "absences": 0}
    changed = False

    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        weather_before = deepcopy(match.get("weather"))
        if _refresh_weather(match, now_local, weather):
            changed = True
            if match.get("weather") != weather_before:
                stats["weather"] += 1
        if not football.offline:
            api_changed, touched = _refresh_api_match(match, now_local, football)
            changed = changed or api_changed
            for key in ("fixture", "lineup", "absences"):
                stats[key] += int(touched[key])

    if changed:
        matches = payload.get("matches") or []
        counts = dict(payload.get("counts") or {})
        counts.update({
            "total": len(matches),
            "jugados": sum(1 for match in matches if match.get("finished")),
            "proximos": sum(1 for match in matches if not match.get("finished")),
        })
        payload["counts"] = counts
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


def run(path: Path = OUTPUT, now: datetime | None = None) -> tuple[bool, dict]:
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
