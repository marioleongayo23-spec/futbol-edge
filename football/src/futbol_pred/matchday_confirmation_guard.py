"""Desactiva falsos ``confirmado`` antes del polling oficial.

Un estado legado/model-only no puede impedir que el refrescador siga buscando el
XI oficial. Este guard se ejecuta antes de API-Football en cada ciclo T-2h.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, OUTPUT, _aware, _parse
from .lineup_authority import is_authoritative_official_lineup


def refresh_payload(payload: dict, now: datetime | None = None):
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    changed = False
    stats = {"audited": 0, "downgraded": 0}
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if not -5 <= minutes <= 120:
            continue
        stats["audited"] += 1
        lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
        if lineup.get("status") != "confirmado" or is_authoritative_official_lineup(lineup):
            continue

        previous = {
            "status": lineup.get("status"),
            "provider": lineup.get("provider"),
            "source_quality": lineup.get("source_quality"),
            "lineup_kind": lineup.get("lineup_kind"),
        }
        lineup["status"] = "estimado"
        lineup["phase"] = "same_day_estimate"
        lineup["lineup_kind"] = "invalid_confirmation_downgraded"
        if not lineup.get("source_quality") or lineup.get("source_quality") == "official":
            lineup["source_quality"] = "unverified_confirmation"
        lineup["display_warning"] = (
            "La alineación figuraba como confirmada sin trazabilidad oficial verificable; "
            "se mantiene solo como estimación mientras continúa el polling del XI oficial."
        )
        lineup["confirmation_guard"] = {
            "checked_at": now_local.isoformat(),
            "downgraded": True,
            "previous": previous,
            "policy": "status confirmado requiere 11+11 + API-Football + fixture id + evidencia oficial",
        }
        match["alineacion"] = lineup
        match["updatedAt"] = now_local.isoformat()
        changed = True
        stats["downgraded"] += 1
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
