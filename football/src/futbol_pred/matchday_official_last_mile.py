"""Polling de última milla del XI oficial entre T-10 y T+2.

El refresco batched prioriza T-75..T-10 para ahorrar cuota. Esta capa cubre el
hueco final cuando el proveedor publica tarde o un feed legado bloqueó intentos
anteriores. Solo actúa si aún no hay una alineación oficial autoritativa.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import (
    MADRID,
    OUTPUT,
    _aware,
    _merge_official_lineup,
    _official_by_side,
    _parse,
    _record_check,
)
from .ingest.api_football import ApiFootballClient
from .lineup_authority import is_authoritative_official_lineup, mark_official_provenance

FROM_MIN = 10
UNTIL_MIN = -2
COOLDOWN_MIN = 3.5


def _age_minutes(value, now_local):
    parsed = _parse(value)
    if not parsed:
        return None
    return max(0.0, (now_local - parsed).total_seconds() / 60.0)


def refresh_payload(payload: dict, now: datetime | None = None, client: ApiFootballClient | None = None):
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    client = client or ApiFootballClient()
    stats = {"candidates": 0, "fixture_found": 0, "official_found": 0, "requests_estimate": 0}
    if client.offline:
        stats["available"] = False
        return False, stats
    stats["available"] = True
    changed = False

    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if not UNTIL_MIN <= minutes <= FROM_MIN:
            continue
        lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
        if is_authoritative_official_lineup(lineup):
            continue
        checks = match.get("operational_checks") if isinstance(match.get("operational_checks"), dict) else {}
        last_age = _age_minutes(checks.get("lineup_checked_at"), now_local)
        if last_age is not None and last_age < COOLDOWN_MIN:
            continue

        stats["candidates"] += 1
        raw = client.find_fixture(match.get("home", ""), match.get("away", ""), kickoff)
        stats["requests_estimate"] += 1
        fixture_id = ((raw or {}).get("fixture") or {}).get("id")
        try:
            fixture_id = int(fixture_id)
        except (TypeError, ValueError):
            fixture_id = None
        if not fixture_id:
            changed = _record_check(match, "lineup", now_local, "fixture_not_found_last_mile") or changed
            continue

        stats["fixture_found"] += 1
        match["api_football_fixture_id"] = fixture_id
        official = client.get_official_lineup(fixture_id)
        stats["requests_estimate"] += 1
        sides = _official_by_side(official or [], match)
        complete = (
            set(sides) == {"local", "visitante"}
            and len((sides.get("local") or {}).get("starters") or []) == 11
            and len((sides.get("visitante") or {}).get("starters") or []) == 11
        )
        changed = _record_check(
            match,
            "lineup",
            now_local,
            "published_last_mile" if complete else "not_published_last_mile",
        ) or changed
        if not complete:
            continue

        if _merge_official_lineup(match, official or [], fixture_id, now_local, minutes):
            mark_official_provenance(match["alineacion"])
            match["alineacion"]["official_poll_window"] = "last_mile"
            match["alineacion"]["fuente"] = "API-Football · fixtures/lineups · last-mile"
            match["updatedAt"] = now_local.isoformat()
            changed = True
            stats["official_found"] += 1
        elif is_authoritative_official_lineup(match.get("alineacion")):
            mark_official_provenance(match["alineacion"])

    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


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


def main():
    ok, stats = run()
    print(json.dumps({"written": ok, **stats}, ensure_ascii=False, sort_keys=True))
    return 0 if not stats.get("feed_issues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
