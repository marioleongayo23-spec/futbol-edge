"""Gate de frescura/coherencia para partidos en T-2h.

No sustituye a los refreshers: certifica si el feed publicado usa inputs lo
bastante recientes para una decisión prepartido y deja una razón explícita para
cada pieza. Un dato puede estar disponible pero no ser fresco; son estados
distintos.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, _aware, _parse

OUTPUT = DATA_DIR / "dashboard.json"


def _age(value, now_local):
    stamp = _parse(value)
    if not stamp:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 60.0)


def _row(ok, state, checked_at=None, max_age=None, detail=None):
    return {
        "ok": bool(ok),
        "state": state,
        "checked_at": checked_at,
        "age_minutes": round(_age(checked_at, _NOW), 1) if checked_at and _age(checked_at, _NOW) is not None else None,
        "max_age_minutes": max_age,
        "detail": detail,
    }


def _names(rows):
    return {
        str(row.get("jugador") or row.get("player") or row.get("name") or "").strip().casefold()
        for row in rows or [] if isinstance(row, dict)
        and (row.get("jugador") or row.get("player") or row.get("name"))
    }


def _official_absence_names(lineup, side):
    rows = lineup.get(f"disponibilidad_{side}") or []
    blocked = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("official"):
            continue
        state = str(row.get("estado") or row.get("status") or "").casefold()
        # Duda/questionable no se trata como baja segura; missing fixture/injury/suspended sí.
        if any(word in state for word in ("question", "duda", "doubt")):
            continue
        name = str(row.get("jugador") or row.get("player") or "").strip().casefold()
        if name:
            blocked.add(name)
    return blocked


def _duplicate_absence_count(lineup):
    total = 0
    for side in ("local", "visitante"):
        rows = lineup.get(f"disponibilidad_{side}") or []
        keys = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            keys.append((
                str(row.get("jugador") or "").casefold(),
                str(row.get("detalle") or "").casefold(),
                str(row.get("estado") or "").casefold(),
            ))
        total += max(0, len(keys) - len(set(keys)))
    return total


def _forecast_matches_kickoff(weather, kickoff):
    try:
        forecast = _parse(weather.get("forecast_for"))
    except AttributeError:
        forecast = None
    if not forecast or not kickoff:
        return False
    return abs((forecast - kickoff).total_seconds()) <= 65 * 60


def _audit_match(match, now_local, minutes):
    lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
    checks = match.get("operational_checks") if isinstance(match.get("operational_checks"), dict) else {}
    weather = match.get("weather") if isinstance(match.get("weather"), dict) else {}
    kickoff = _parse(match.get("kickoff"))
    audit = {}

    weather_at = checks.get("weather_checked_at") or weather.get("source_updated_at")
    weather_age = _age(weather_at, now_local)
    weather_ok = weather_age is not None and weather_age <= 10 and _forecast_matches_kickoff(weather, kickoff)
    audit["weather"] = {
        "ok": weather_ok,
        "state": "fresh_kickoff_forecast" if weather_ok else "stale_or_wrong_hour",
        "checked_at": weather_at,
        "age_minutes": round(weather_age, 1) if weather_age is not None else None,
        "max_age_minutes": 10,
        "forecast_for": weather.get("forecast_for"),
    }

    abs_at = checks.get("absences_checked_at")
    abs_age = _age(abs_at, now_local)
    abs_ok = abs_age is not None and abs_age <= 95
    audit["absences"] = {
        "ok": abs_ok,
        "state": "fresh" if abs_ok else "stale_or_unchecked",
        "checked_at": abs_at,
        "age_minutes": round(abs_age, 1) if abs_age is not None else None,
        "max_age_minutes": 95,
    }

    status = lineup.get("status") or "sin confirmar"
    probable_at = lineup.get("critical_probable_checked_at") or lineup.get("source_updated_at")
    probable_age = _age(probable_at, now_local)
    if status == "confirmado":
        probable_ok = True
        probable_state = "superseded_by_official"
    else:
        probable_ok = probable_age is not None and probable_age <= 15
        probable_state = "fresh" if probable_ok else "stale_probable"
    audit["probable_lineup"] = {
        "ok": probable_ok,
        "state": probable_state,
        "checked_at": probable_at,
        "age_minutes": round(probable_age, 1) if probable_age is not None else None,
        "max_age_minutes": 15,
        "lineup_status": status,
        "source_quality": lineup.get("source_quality"),
    }

    lineup_at = checks.get("lineup_checked_at") or lineup.get("official_poll_at")
    lineup_age = _age(lineup_at, now_local)
    official_due = minutes <= 75
    official_ok = (not official_due) or (lineup_age is not None and lineup_age <= 10)
    audit["official_lineup"] = {
        "ok": official_ok,
        "state": "confirmed" if status == "confirmado" else ("fresh_poll_no_xi_yet" if official_ok and official_due else "awaiting_window" if not official_due else "stale_poll"),
        "checked_at": lineup_at,
        "age_minutes": round(lineup_age, 1) if lineup_age is not None else None,
        "max_age_minutes": 10 if official_due else None,
        "required_now": official_due,
    }

    odds = match.get("odds")
    market = match.get("market_hot_refresh") if isinstance(match.get("market_hot_refresh"), dict) else {}
    market_at = market.get("checked_at") or (((odds or {}).get("meta") or {}).get("checked_at") if isinstance(odds, dict) else None)
    market_age = _age(market_at, now_local)
    try:
        market_ttl = int(market.get("ttl_minutes") or (((odds or {}).get("meta") or {}).get("ttl_minutes")) or 5)
    except (TypeError, ValueError):
        market_ttl = 5
    odds_real = isinstance(odds, dict) and isinstance(odds.get("1x2"), dict)
    market_ok = odds_real and market_age is not None and market_age <= max(7, market_ttl + 2)
    audit["odds"] = {
        "ok": market_ok,
        "state": "fresh" if market_ok else "missing_or_stale",
        "checked_at": market_at,
        "age_minutes": round(market_age, 1) if market_age is not None else None,
        "max_age_minutes": max(7, market_ttl + 2),
        "provider": market.get("provider"),
    }

    props_at = lineup.get("player_props_checked_at") or checks.get("player_props_checked_at")
    props_age = _age(props_at, now_local)
    props_count = len(lineup.get("clave_local") or []) + len(lineup.get("clave_visitante") or [])
    props_ok = props_age is not None and props_age <= 20 and props_count >= 16
    audit["player_props"] = {
        "ok": props_ok,
        "state": "fresh" if props_ok else "missing_stale_or_low_sample",
        "checked_at": props_at,
        "age_minutes": round(props_age, 1) if props_age is not None else None,
        "max_age_minutes": 20,
        "real_players": props_count,
        "target_players": 22,
    }

    pred = match.get("prediction_live_refresh") if isinstance(match.get("prediction_live_refresh"), dict) else {}
    pred_at = pred.get("checked_at") or ((match.get("prediction_confidence") or {}).get("refreshed_at") if isinstance(match.get("prediction_confidence"), dict) else None)
    pred_age = _age(pred_at, now_local)
    pred_ok = pred_age is not None and pred_age <= 10
    audit["prediction"] = {
        "ok": pred_ok,
        "state": "fresh" if pred_ok else "stale",
        "checked_at": pred_at,
        "age_minutes": round(pred_age, 1) if pred_age is not None else None,
        "max_age_minutes": 10,
    }

    conflicts = []
    for side in ("local", "visitante"):
        starters = {str(name).strip().casefold(): str(name) for name in lineup.get(side) or []}
        blocked = _official_absence_names(lineup, side)
        for key in sorted(blocked & set(starters)):
            conflicts.append(f"{side}: {starters[key]} figura en XI y baja oficial")
    duplicates = _duplicate_absence_count(lineup)
    if duplicates:
        conflicts.append(f"{duplicates} bajas duplicadas")

    missing = [name for name, row in audit.items() if not row.get("ok")]
    if conflicts:
        level = "critical"
    elif missing:
        level = "warning"
    else:
        level = "ready"
    return {
        "status": level,
        "checked_at": now_local.isoformat(),
        "minutes_to_kickoff": round(minutes, 1),
        "all_fresh": level == "ready",
        "requires_retry": level != "ready",
        "missing_or_stale": missing,
        "hard_conflicts": conflicts,
        "checks": audit,
        "policy": "T-2h: weather/predicción <=10m, probable <=15m, XI oficial <=10m desde T-75, bajas <=95m, odds según TTL, props >=16/22 y <=20m",
    }


def refresh_payload(payload: dict, now: datetime | None = None):
    global _NOW
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    _NOW = now_local
    changed = False
    summary = {"audited": 0, "ready": 0, "warning": 0, "critical": 0}
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        minutes = (kickoff - now_local).total_seconds() / 60.0
        if not -5 <= minutes <= 120:
            continue
        result = _audit_match(match, now_local, minutes)
        if match.get("matchday_freshness") != result:
            match["matchday_freshness"] = result
            changed = True
        summary["audited"] += 1
        summary[result["status"]] += 1
    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, summary


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


_NOW = datetime.now(timezone.utc).astimezone(MADRID)

if __name__ == "__main__":
    raise SystemExit(main())
