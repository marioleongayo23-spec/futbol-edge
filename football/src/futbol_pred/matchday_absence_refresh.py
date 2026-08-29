"""Control autoritativo de bajas durante las 24 h previas al partido.

Las lesiones/sanciones ya no esperan a T-2h. Se consulta por lotes con una
cadencia adaptativa para no quemar cuota:
- T-24h..T-6h: como máximo cada 180 min;
- T-6h..T-2h: como máximo cada 90 min;
- T-2h..kickoff: como máximo cada 45 min.

La respuesta se deduplica antes de sustituir el bloque de disponibilidad. El
último XI oficial visible se sanea después por matchday_lineup_baseline y por la
barrera de integridad crítica.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from . import hot_refresh as legacy
from .ingest.api_football import ApiFootballClient
from .ingest.api_football_quota import get_absences_batch

OUTPUT = DATA_DIR / "dashboard.json"
MADRID = legacy.MADRID
LOOKAHEAD_MIN = 24 * 60


def _parse(value):
    return legacy._parse(value)


def _age_min(value, now_local):
    stamp = _parse(value)
    if not stamp:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 60.0)


def _max_age_min(minutes_to_kickoff: float) -> int:
    if minutes_to_kickoff <= 120:
        return 45
    if minutes_to_kickoff <= 360:
        return 90
    return 180


def _fixture_id(match):
    for value in (
        match.get("api_football_fixture_id"),
        (match.get("alineacion") or {}).get("official_fixture_id"),
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _dedupe(rows):
    out = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("team") or "").strip().casefold(),
            str(row.get("jugador") or row.get("player") or row.get("name") or "").strip().casefold(),
            str(row.get("detalle") or row.get("reason") or "").strip().casefold(),
            str(row.get("estado") or row.get("status") or "").strip().casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _remaining(payload):
    try:
        return int(((payload.get("source_health") or {}).get("api_football") or {}).get("daily_remaining"))
    except (TypeError, ValueError):
        return None


def refresh_payload(payload: dict, now: datetime | None = None, client: ApiFootballClient | None = None):
    now_local = legacy._aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    client = client or ApiFootballClient()
    due = []
    changed = False
    stats = {"tracked": 0, "critical": 0, "queried": 0, "refreshed": 0, "resolved_fixture_ids": 0}

    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff:
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if not -5 <= minutes <= LOOKAHEAD_MIN:
            continue
        stats["tracked"] += 1
        if minutes <= 120:
            stats["critical"] += 1
        last = ((match.get("operational_checks") or {}).get("absences_checked_at"))
        age = _age_min(last, now_local)
        if age is not None and age < _max_age_min(minutes):
            continue
        due.append(match)

    if not due or client.offline:
        return changed, stats
    remaining = _remaining(payload)
    if remaining is not None and remaining <= 10:
        stats["quota_guard"] = "reserved_for_lineup"
        return changed, stats

    ids = []
    by_id = {}
    for match in due:
        fixture_id = _fixture_id(match)
        if fixture_id is None:
            kickoff = _parse(match.get("kickoff"))
            raw = client.find_fixture(match.get("home", ""), match.get("away", ""), kickoff)
            fixture_id = (((raw or {}).get("fixture") or {}).get("id"))
            try:
                fixture_id = int(fixture_id)
            except (TypeError, ValueError):
                fixture_id = None
            if fixture_id is not None:
                match["api_football_fixture_id"] = fixture_id
                lineup = match.get("alineacion") or {}
                lineup["official_fixture_id"] = fixture_id
                match["alineacion"] = lineup
                changed = True
                stats["resolved_fixture_ids"] += 1
        if fixture_id is not None:
            ids.append(fixture_id)
            by_id[fixture_id] = match
        else:
            if legacy._record_check(match, "absences", now_local, "fixture_not_found"):
                changed = True

    if ids:
        raw_by_id = get_absences_batch(client, ids)
        stats["queried"] = 1
        for fixture_id, match in by_id.items():
            raw_rows = raw_by_id.get(fixture_id)
            if raw_rows is None:
                if legacy._record_check(match, "absences", now_local, "unavailable"):
                    changed = True
                continue
            rows = _dedupe(raw_rows)
            if legacy._merge_absences(match, rows, now_local):
                changed = True
            if legacy._record_check(match, "absences", now_local, "ok"):
                changed = True
            stats["refreshed"] += 1

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
