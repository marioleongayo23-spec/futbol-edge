"""Gate T-2h de frescura, autoridad y publicabilidad.

Certifica que un partido usa inputs recientes y coherentes. También actúa como
última barrera de publicación: si el gate no está ``ready`` conserva las
probabilidades del modelo, pero fuerza ``no_pick`` para no presentar una apuesta
como publicable con datos críticos incompletos.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .config import DATA_DIR
from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, _aware, _parse
from .lineup_authority import is_authoritative_official_lineup

OUTPUT = DATA_DIR / "dashboard.json"
TRUSTED_PROBABLE_QUALITIES = {"media_grounded", "official"}


def _age(value, now_local):
    stamp = _parse(value)
    if not stamp:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 60.0)


def _parse_forecast_local(value) -> datetime | None:
    """Open-Meteo devuelve la hora solicitada en Europe/Madrid sin offset.

    Los timestamps operativos del feed sí suelen venir con offset/UTC. Por eso
    ``forecast_for`` necesita una semántica distinta a ``hot_refresh._parse``:
    una fecha naive se interpreta como hora local de Madrid, no como UTC.
    """
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=MADRID)
    return parsed.astimezone(MADRID)


def _official_absence_names(lineup, side):
    rows = lineup.get(f"disponibilidad_{side}") or []
    blocked = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("official"):
            continue
        state = str(row.get("estado") or row.get("status") or "").casefold()
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
        forecast = _parse_forecast_local(weather.get("forecast_for"))
    except AttributeError:
        forecast = None
    if not forecast or not kickoff:
        return False
    return abs((forecast - kickoff.astimezone(MADRID)).total_seconds()) <= 65 * 60


def _trusted_probable(lineup: dict) -> bool:
    quality = str(lineup.get("source_quality") or "").casefold()
    kind = str(lineup.get("lineup_kind") or "").casefold()
    status = str(lineup.get("status") or "").casefold()
    return (
        status == "probable"
        and len(lineup.get("local") or []) == 11
        and len(lineup.get("visitante") or []) == 11
        and (quality in TRUSTED_PROBABLE_QUALITIES or kind == "source_grounded_probable")
    )


def _audit_match(match, now_local, minutes):
    lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
    checks = match.get("operational_checks") if isinstance(match.get("operational_checks"), dict) else {}
    weather = match.get("weather") if isinstance(match.get("weather"), dict) else {}
    kickoff = _parse(match.get("kickoff"))
    audit = {}
    authoritative_official = is_authoritative_official_lineup(lineup)

    weather_at = checks.get("weather_checked_at") or weather.get("source_updated_at")
    weather_age = _age(weather_at, now_local)
    weather_hour_ok = _forecast_matches_kickoff(weather, kickoff)
    weather_ok = weather_age is not None and weather_age <= 10 and weather_hour_ok
    audit["weather"] = {
        "ok": weather_ok,
        "state": "fresh_kickoff_forecast" if weather_ok else ("wrong_kickoff_hour" if weather_age is not None and weather_age <= 10 else "stale_or_unchecked"),
        "checked_at": weather_at,
        "age_minutes": round(weather_age, 1) if weather_age is not None else None,
        "max_age_minutes": 10,
        "forecast_for": weather.get("forecast_for"),
        "kickoff_hour_match": weather_hour_ok,
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
    if authoritative_official:
        probable_ok = True
        probable_state = "superseded_by_authoritative_official"
    else:
        probable_ok = (
            probable_age is not None
            and probable_age <= 15
            and _trusted_probable(lineup)
        )
        if status == "confirmado":
            probable_state = "invalid_confirmation_provenance"
        elif probable_ok:
            probable_state = "fresh_source_grounded_probable"
        elif probable_age is not None and probable_age <= 15:
            probable_state = "fresh_but_untrusted_estimate"
        else:
            probable_state = "stale_or_untrusted_probable"
    audit["probable_lineup"] = {
        "ok": probable_ok,
        "state": probable_state,
        "checked_at": probable_at,
        "age_minutes": round(probable_age, 1) if probable_age is not None else None,
        "max_age_minutes": 15,
        "lineup_status": status,
        "source_quality": lineup.get("source_quality"),
        "lineup_kind": lineup.get("lineup_kind"),
        "authoritative_official": authoritative_official,
    }

    lineup_at = checks.get("lineup_checked_at") or lineup.get("official_poll_at")
    lineup_age = _age(lineup_at, now_local)
    poll_due = minutes <= 75
    official_mandatory = minutes <= 15
    if authoritative_official:
        official_ok = True
        official_state = "confirmed_authoritative"
        official_max_age = None  # un XI oficial no caduca por no volver a consultarlo
    elif official_mandatory:
        official_ok = False
        official_state = "official_missing_last_mile" if status != "confirmado" else "invalid_confirmation_provenance"
        official_max_age = 10
    elif poll_due:
        official_ok = lineup_age is not None and lineup_age <= 10
        official_state = "fresh_poll_no_xi_yet" if official_ok else "stale_poll"
        official_max_age = 10
    else:
        official_ok = True
        official_state = "awaiting_official_window"
        official_max_age = None
    audit["official_lineup"] = {
        "ok": official_ok,
        "state": official_state,
        "checked_at": lineup_at,
        "age_minutes": round(lineup_age, 1) if lineup_age is not None else None,
        "max_age_minutes": official_max_age,
        "poll_required_now": poll_due,
        "official_required_now": official_mandatory,
        "authoritative": authoritative_official,
        "provider": lineup.get("provider"),
        "official_fixture_id": lineup.get("official_fixture_id"),
    }

    odds = match.get("odds")
    odds_dict = odds if isinstance(odds, dict) else {}
    odds_meta = odds_dict.get("meta") if isinstance(odds_dict.get("meta"), dict) else {}
    market = match.get("market_hot_refresh") if isinstance(match.get("market_hot_refresh"), dict) else {}
    market_at = market.get("checked_at") or odds_meta.get("checked_at")
    market_age = _age(market_at, now_local)
    try:
        market_ttl = int(market.get("ttl_minutes") or odds_meta.get("ttl_minutes") or 5)
    except (TypeError, ValueError):
        market_ttl = 5
    odds_real = isinstance(odds_dict.get("1x2"), dict)
    market_ok = odds_real and market_age is not None and market_age <= max(7, market_ttl + 2)
    if market_ok:
        market_state = "fresh"
    elif isinstance(odds, str):
        market_state = "legacy_pending_or_unavailable"
    else:
        market_state = "missing_or_stale"
    audit["odds"] = {
        "ok": market_ok,
        "state": market_state,
        "checked_at": market_at,
        "age_minutes": round(market_age, 1) if market_age is not None else None,
        "max_age_minutes": max(7, market_ttl + 2),
        "provider": market.get("provider"),
        "raw_state": odds if isinstance(odds, str) else None,
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
    if status == "confirmado" and not authoritative_official:
        conflicts.append("XI marcado como confirmado sin procedencia oficial verificable")
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
        "policy": "T-2h: meteo/predicción <=10m, probable fiable <=15m, polling oficial <=10m desde T-75, XI oficial obligatorio desde T-15, bajas <=95m, odds según TTL, props >=16/22 y <=20m",
    }


def _apply_publication_gate(match: dict, result: dict, now_local: datetime) -> bool:
    """Bloquea una recomendación si los datos T-2h no están listos.

    No toca ``probs`` ni ``model_probs``. Solo limita la confianza publicada y
    la elegibilidad de apuesta; el siguiente ciclo predictivo puede recalcularla
    cuando el gate vuelva a ``ready``.
    """
    before = deepcopy({
        "prediction_confidence": match.get("prediction_confidence"),
        "recommendation": match.get("recommendation"),
    })
    confidence = dict(match.get("prediction_confidence") or {})
    recommendation = dict(match.get("recommendation") or {})

    if result.get("status") == "ready":
        for key in (
            "data_freshness_gate_applied",
            "data_freshness_gate_status",
            "raw_score_before_freshness_gate",
            "data_freshness_missing",
            "data_freshness_conflicts",
        ):
            confidence.pop(key, None)
        recommendation.pop("data_freshness_gate", None)
        match["prediction_confidence"] = confidence
        match["recommendation"] = recommendation
        return before != {
            "prediction_confidence": match.get("prediction_confidence"),
            "recommendation": match.get("recommendation"),
        }

    raw_score = confidence.get("score")
    try:
        raw_score_num = float(raw_score)
    except (TypeError, ValueError):
        raw_score_num = None
    cap = 35 if result.get("status") == "critical" else 54
    if raw_score_num is not None:
        confidence["raw_score_before_freshness_gate"] = round(raw_score_num, 1)
        confidence["score"] = min(cap, int(round(raw_score_num)))
        confidence["level"] = "baja" if confidence["score"] < 55 else "media"
    confidence["data_freshness_gate_applied"] = True
    confidence["data_freshness_gate_status"] = result.get("status")
    confidence["data_freshness_missing"] = list(result.get("missing_or_stale") or [])
    confidence["data_freshness_conflicts"] = list(result.get("hard_conflicts") or [])

    gate_reason = "gate T-2h no listo"
    details = list(result.get("missing_or_stale") or []) + list(result.get("hard_conflicts") or [])
    if details:
        gate_reason += ": " + ", ".join(details)
    reasons = [str(reason) for reason in (recommendation.get("reasons") or []) if reason]
    if gate_reason not in reasons:
        reasons.append(gate_reason)
    recommendation.update({
        "decision": "no_pick",
        "label": "Sin apuesta recomendada · datos por completar",
        "reasons": reasons,
        "policy": "abstención automática: el gate T-2h debe estar ready para publicar apuesta",
        "refreshed_at": now_local.isoformat(),
        "data_freshness_gate": {
            "status": result.get("status"),
            "checked_at": result.get("checked_at"),
            "missing_or_stale": list(result.get("missing_or_stale") or []),
            "hard_conflicts": list(result.get("hard_conflicts") or []),
        },
    })
    match["prediction_confidence"] = confidence
    match["recommendation"] = recommendation
    return before != {
        "prediction_confidence": match.get("prediction_confidence"),
        "recommendation": match.get("recommendation"),
    }


def refresh_payload(payload: dict, now: datetime | None = None):
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    changed = False
    summary = {"audited": 0, "ready": 0, "warning": 0, "critical": 0, "publication_blocked": 0}
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
        if _apply_publication_gate(match, result, now_local):
            changed = True
        if result["status"] != "ready":
            summary["publication_blocked"] += 1
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


if __name__ == "__main__":
    raise SystemExit(main())
