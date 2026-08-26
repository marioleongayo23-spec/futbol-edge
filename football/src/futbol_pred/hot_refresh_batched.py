"""Hot-refresh optimizado para la cuota Free de API-Football.

Mantiene la semántica del refresco ligero, pero evita una petición por partido:
- resuelve y persiste el fixture id una sola vez por jornada;
- actualiza estado/marcador/XI con ``/fixtures?ids=...`` en lotes de hasta 20;
- consulta bajas con ``/injuries?ids=...`` también por lotes;
- en vivo limita el polling de API-Football a ~20 min salvo que coincida una
  ventana de XI, mientras el workflow puede seguir despertando cada 10 min para
  clima, cobertura y otras fuentes gratuitas.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from . import hot_refresh as legacy
from .context import WeatherClient
from .feed_quality import load_feed, write_feed_safely
from .ingest.api_football import ApiFootballClient
from .ingest.api_football_quota import get_absences_batch

# API-Football publica injuries con una cadencia mucho menor que los datos live.
# Dos comprobaciones (T-6h y T-60) conservan utilidad y evitan quemar cuota Free.
ABSENCE_TARGETS_MIN = (360, 60)
# Con un scheduler nominal de 10 min, 18 min produce una llamada live cada ~20.
LIVE_POLL_INTERVAL_MIN = 18
# Estado/marcador: empezar 15 min antes y seguir hasta 3h después del kickoff.
LIVE_FROM_MIN = 15
LIVE_UNTIL_MIN = -180


def _last_fixture_check_age_min(match: dict, now_local: datetime) -> float | None:
    value = ((match.get("operational_checks") or {}).get("fixture_checked_at"))
    checked = legacy._parse(value)
    if checked is None:
        return None
    return max(0.0, (now_local - checked).total_seconds() / 60)


def _poll_plan(match: dict, now_local: datetime) -> dict | None:
    kickoff = legacy._parse(match.get("kickoff"))
    if kickoff is None or kickoff.date() != now_local.date():
        return None
    minutes = (kickoff - now_local).total_seconds() / 60
    finished = bool(match.get("finished"))
    wants_lineup = (
        not finished
        and (match.get("alineacion") or {}).get("status") != "confirmado"
        and legacy._near_target(minutes, legacy.LINEUP_TARGETS_MIN)
    )
    wants_absences = (
        not finished
        and legacy._near_target(minutes, ABSENCE_TARGETS_MIN)
    )
    live_window = not finished and LIVE_UNTIL_MIN <= minutes <= LIVE_FROM_MIN
    age = _last_fixture_check_age_min(match, now_local)
    wants_live = live_window and (age is None or age >= LIVE_POLL_INTERVAL_MIN)
    return {
        "kickoff": kickoff,
        "minutes": minutes,
        "wants_live": wants_live,
        "wants_lineup": wants_lineup,
        "wants_absences": wants_absences,
        "relevant": wants_live or wants_lineup or wants_absences,
    }


def _fixture_id(match: dict) -> int | None:
    candidates = [
        match.get("api_football_fixture_id"),
        (match.get("alineacion") or {}).get("official_fixture_id"),
    ]
    for value in candidates:
        try:
            fixture_id = int(value)
        except (TypeError, ValueError):
            continue
        if fixture_id > 0:
            return fixture_id
    return None


def _cache_known_fixture_ids(matches: list[dict]) -> bool:
    changed = False
    for match in matches:
        if match.get("api_football_fixture_id"):
            continue
        fixture_id = _fixture_id(match)
        if fixture_id:
            match["api_football_fixture_id"] = fixture_id
            changed = True
    return changed


def _resolve_today_fixture_ids(
    matches: list[dict],
    plans: dict[int, dict],
    client: ApiFootballClient,
) -> tuple[bool, dict[int, dict]]:
    """Resuelve todos los ids del día con una única caché ``fixtures?date``.

    Solo se activa cuando al menos un partido necesita API-Football. Resolver el
    resto de partidos del mismo día no añade HTTP: ``find_fixture`` reutiliza la
    respuesta diaria del cliente y deja los ids preparados para horas después.
    """
    relevant = [match for match in matches if (plans.get(id(match)) or {}).get("relevant")]
    if not relevant:
        return False, {}

    changed = _cache_known_fixture_ids(matches)
    if all(_fixture_id(match) for match in matches):
        return changed, {}

    fresh_raw: dict[int, dict] = {}
    for match in matches:
        if _fixture_id(match):
            continue
        plan = plans.get(id(match))
        if plan is None:
            continue
        raw = client.find_fixture(
            match.get("home", ""),
            match.get("away", ""),
            plan["kickoff"],
        )
        fixture_id = ((raw or {}).get("fixture") or {}).get("id")
        try:
            fixture_id = int(fixture_id)
        except (TypeError, ValueError):
            fixture_id = None
        if fixture_id:
            match["api_football_fixture_id"] = fixture_id
            fresh_raw[id(match)] = raw
            changed = True
    return changed, fresh_raw


def _apply_fixture(match: dict, raw: dict | None, now_local: datetime) -> tuple[bool, bool]:
    """Aplica estado/marcador de una respuesta real de ``/fixtures``."""
    if raw is None:
        return legacy._record_check(match, "fixture", now_local, "unavailable"), False

    fixture = raw.get("fixture") or {}
    fixture_id = fixture.get("id")
    changed = legacy._record_check(
        match, "fixture", now_local, "ok" if fixture_id else "not_found"
    )
    if not fixture_id:
        return changed, False

    touched = False
    status = str((fixture.get("status") or {}).get("short") or match.get("status") or "")
    goals = raw.get("goals") or {}
    home_goals, away_goals = goals.get("home"), goals.get("away")
    if status and status != match.get("status"):
        match["status"] = status
        changed = touched = True
    if home_goals is not None and away_goals is not None:
        score = [home_goals, away_goals]
        if match.get("live_score") != score:
            match["live_score"] = score
            changed = touched = True
    if status.upper() in legacy.FINISHED and home_goals is not None and away_goals is not None:
        score = [home_goals, away_goals]
        if not match.get("finished") or match.get("result") != score:
            match["finished"] = True
            match["result"] = score
            match["engine"] = "resultado-real"
            changed = touched = True
    return changed, touched


def _mark_missing_fixture(match: dict, plan: dict, now_local: datetime) -> bool:
    changed = legacy._record_check(match, "fixture", now_local, "not_found")
    if plan.get("wants_lineup"):
        changed = legacy._record_check(match, "lineup", now_local, "fixture_not_found") or changed
    if plan.get("wants_absences"):
        changed = legacy._record_check(match, "absences", now_local, "fixture_not_found") or changed
    return changed


def _refresh_api_batched(
    matches: list[dict],
    now_local: datetime,
    client: ApiFootballClient,
) -> tuple[bool, dict]:
    stats = {"fixture": 0, "lineup": 0, "absences": 0}
    plans = {
        id(match): plan
        for match in matches
        if isinstance(match, dict)
        for plan in [_poll_plan(match, now_local)]
        if plan is not None
    }
    if not any(plan["relevant"] for plan in plans.values()):
        return False, stats

    changed, fresh_raw = _resolve_today_fixture_ids(matches, plans, client)

    detail_ids = []
    absence_ids = []
    for match in matches:
        plan = plans.get(id(match))
        fixture_id = _fixture_id(match)
        if not plan or not plan["relevant"] or not fixture_id:
            continue
        if plan["wants_live"] or plan["wants_lineup"]:
            detail_ids.append(fixture_id)
        if plan["wants_absences"]:
            absence_ids.append(fixture_id)

    details = client.get_fixture_details(detail_ids) if detail_ids else {}
    absences_by_fixture = get_absences_batch(client, absence_ids) if absence_ids else {}

    for match in matches:
        if not isinstance(match, dict):
            continue
        plan = plans.get(id(match))
        if not plan or not plan["relevant"]:
            continue
        fixture_id = _fixture_id(match)
        if not fixture_id:
            changed = _mark_missing_fixture(match, plan, now_local) or changed
            continue

        touched_any = False
        # Una llamada batch de fixtures sirve a la vez para live y XI. En una
        # primera resolución T-6h, la respuesta por fecha también es evidencia
        # real suficiente para estado/id sin añadir otra petición.
        raw = None
        if plan["wants_live"] or plan["wants_lineup"]:
            raw = details.get(fixture_id)
        elif id(match) in fresh_raw:
            raw = fresh_raw[id(match)]
        if raw is not None or plan["wants_live"] or plan["wants_lineup"]:
            fixture_changed, fixture_touched = _apply_fixture(match, raw, now_local)
            changed = fixture_changed or changed
            if fixture_touched:
                stats["fixture"] += 1
                touched_any = True

        if plan["wants_absences"]:
            absences = absences_by_fixture.get(fixture_id)
            check_result = "ok" if absences is not None else "unavailable"
            changed = legacy._record_check(match, "absences", now_local, check_result) or changed
            if absences is not None and legacy._merge_absences(match, absences, now_local):
                stats["absences"] += 1
                changed = touched_any = True

        if plan["wants_lineup"]:
            detail = details.get(fixture_id)
            if detail is None:
                changed = legacy._record_check(match, "lineup", now_local, "unavailable") or changed
            else:
                official = client.lineup_from_fixture(detail)
                published = bool(legacy._official_by_side(official or [], match))
                changed = legacy._record_check(
                    match, "lineup", now_local,
                    "published" if published else "not_published",
                ) or changed
                if legacy._merge_official_lineup(
                    match, official or [], fixture_id, now_local, plan["minutes"]
                ):
                    stats["lineup"] += 1
                    changed = touched_any = True

        if touched_any:
            match["updatedAt"] = now_local.isoformat()

    return changed, stats


def refresh_payload(
    payload: dict,
    now: datetime | None = None,
    weather_client: WeatherClient | None = None,
    football_client: ApiFootballClient | None = None,
) -> tuple[bool, dict]:
    """Muta un feed válido usando batches cuando el cliente es API-Football real."""
    now_local = legacy._aware(now or datetime.now(timezone.utc)).astimezone(legacy.MADRID)
    weather = weather_client or WeatherClient()
    football = football_client or ApiFootballClient()
    stats = {"weather": 0, "fixture": 0, "lineup": 0, "absences": 0}
    changed = False
    matches = [match for match in (payload.get("matches") or []) if isinstance(match, dict)]

    for match in matches:
        weather_before = deepcopy(match.get("weather"))
        if legacy._refresh_weather(match, now_local, weather):
            changed = True
            if match.get("weather") != weather_before:
                stats["weather"] += 1

    if not getattr(football, "offline", True):
        # Clientes de tests/terceros que no implementan el contrato batch siguen
        # usando el comportamiento anterior, lo que mantiene compatibilidad.
        if isinstance(football, ApiFootballClient):
            api_changed, api_stats = _refresh_api_batched(matches, now_local, football)
            changed = api_changed or changed
            for key in ("fixture", "lineup", "absences"):
                stats[key] += api_stats[key]
        else:
            for match in matches:
                api_changed, touched = legacy._refresh_api_match(match, now_local, football)
                changed = api_changed or changed
                for key in ("fixture", "lineup", "absences"):
                    stats[key] += int(touched[key])

    if changed:
        all_matches = payload.get("matches") or []
        counts = dict(payload.get("counts") or {})
        counts.update({
            "total": len(all_matches),
            "jugados": sum(1 for match in all_matches if isinstance(match, dict) and match.get("finished")),
            "proximos": sum(1 for match in all_matches if isinstance(match, dict) and not match.get("finished")),
        })
        payload["counts"] = counts
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


def run(path=legacy.OUTPUT, now: datetime | None = None) -> tuple[bool, dict]:
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
