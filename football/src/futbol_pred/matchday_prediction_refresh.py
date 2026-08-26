"""Recálculo ligero de la predicción para partidos del día.

Se ejecuta después de clima/XI/bajas/cuotas y evita esperar al pipeline pesado:
- reaplica el clima sobre el xG BASE sin acumular multiplicadores;
- recalcula O/U y BTTS con ese xG;
- sincroniza value O/U con la última cuota real;
- recalcula impacto del once, confianza, completitud y regla no-pick;
- deja trazabilidad explícita de cuándo reaccionó la predicción.

No reentrena Dixon-Coles/Elo ni altera ``model_probs``. Por diseño, XI/clima no
mueven directamente el 1X2 puro hasta superar sus gates históricos; la cuota sí
puede recalibrar ``probs`` en ``matchday_market_refresh`` usando la política ya
validada por el pipeline completo.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math

from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, OUTPUT, _aware, _parse


def _num(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _same_pair(left, right, tolerance=0.015) -> bool:
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != 2 or len(right) != 2:
        return False
    try:
        return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right))
    except (TypeError, ValueError):
        return False


def weather_multipliers(weather: dict | None) -> dict:
    weather = weather or {}
    wind = _num(weather.get("wind_kmh"))
    rain = _num(weather.get("precipitation_mm"))
    rain_prob = _num(weather.get("precipitation_probability_pct"))
    apparent = _num(weather.get("apparent_temperature_c"), _num(weather.get("temperature_c")))
    goals = shots = 1.0
    fouls = cards = 1.0
    reasons = []
    if wind >= 35:
        goals *= .92; shots *= .92; fouls *= 1.03; cards *= 1.04
        reasons.append(f"viento fuerte {wind:.0f} km/h")
    elif wind >= 25:
        goals *= .96; shots *= .96; fouls *= 1.02; cards *= 1.03
        reasons.append(f"viento {wind:.0f} km/h")
    if rain >= 4.0:
        goals *= .94; shots *= .95; fouls *= 1.05; cards *= 1.06
        reasons.append(f"lluvia fuerte {rain:.1f} mm/h")
    elif rain >= 1.5 or rain_prob >= 75:
        goals *= .97; shots *= .97; fouls *= 1.03; cards *= 1.04
        reasons.append("lluvia probable/intensa")
    if apparent >= 34:
        goals *= .98; shots *= .97; fouls *= 1.02
        reasons.append(f"estrés térmico {apparent:.0f} °C aparente")
    return {
        "goals": round(max(.88, min(1.02, goals)), 4),
        "shots": round(max(.88, min(1.02, shots)), 4),
        "fouls": round(max(.98, min(1.10, fouls)), 4),
        "cards": round(max(.98, min(1.12, cards)), 4),
        "reasons": reasons,
    }


def _poisson_cdf(k: int, mean: float) -> float:
    mean = max(0.0, float(mean))
    term = math.exp(-mean)
    total = term
    for i in range(1, max(0, int(k)) + 1):
        term *= mean / i
        total += term
    return min(1.0, max(0.0, total))


def _over(mean: float, line: float) -> float:
    return 1.0 - _poisson_cdf(math.floor(line), mean)


def _btts(home: float, away: float) -> float:
    return 1.0 - math.exp(-home) - math.exp(-away) + math.exp(-(home + away))


def _weather_base_xg(match: dict, previous: dict) -> list[float] | None:
    xg = match.get("xg")
    if not isinstance(xg, list) or len(xg) != 2:
        return None
    old_xg = previous.get("xg") or {}
    if previous.get("applied") and _same_pair(xg, old_xg.get("after")) and isinstance(old_xg.get("before"), list):
        return [float(old_xg["before"][0]), float(old_xg["before"][1])]
    return [float(xg[0]), float(xg[1])]


def _base_stat(row: dict, previous_factor: float, previous_applied: bool) -> tuple[float, float] | None:
    try:
        home, away = float(row["home"]), float(row["away"])
    except (KeyError, TypeError, ValueError):
        return None
    if previous_applied and previous_factor and abs(previous_factor - 1.0) > 1e-9:
        home /= previous_factor
        away /= previous_factor
    return home, away


def _remove_vig(prices: list[float]) -> list[float]:
    implied = [1.0 / float(price) for price in prices]
    total = sum(implied) or 1.0
    return [value / total for value in implied]


def _sync_ou_value(match: dict, model_over: float, source_stamp: str) -> None:
    rows = [dict(row) for row in (match.get("value") or []) if isinstance(row, dict)]
    odds = match.get("odds") if isinstance(match.get("odds"), dict) else {}
    ou_odds = ((odds.get("ou25") or {}).get("odds") if isinstance(odds.get("ou25"), dict) else {}) or {}
    over_price, under_price = _num(ou_odds.get("over"), 0), _num(ou_odds.get("under"), 0)
    probability_over = model_over
    if over_price > 1 and under_price > 1:
        fair = _remove_vig([over_price, under_price])
        calibration = match.get("market_calibration") if isinstance(match.get("market_calibration"), dict) else {}
        try:
            weight = max(0.0, min(1.0, float(calibration.get("model_weight", 1.0))))
        except (TypeError, ValueError):
            weight = 1.0
        probability_over = weight * model_over + (1.0 - weight) * fair[0]
    found = set()
    for row in rows:
        if row.get("market") != "ou25":
            continue
        selection = str(row.get("selection") or "").casefold()
        probability = probability_over if selection == "over" else 1.0 - probability_over if selection == "under" else None
        price = over_price if selection == "over" else under_price if selection == "under" else _num(row.get("odds"), 0)
        if probability is None:
            continue
        row["modelProb"] = round(probability, 4)
        if price > 1:
            row["odds"] = round(price, 3)
            row["edge"] = round(probability * price - 1.0, 4)
        row["weather_adjusted"] = True
        row["prediction_refreshed_at"] = source_stamp
        found.add(selection)
    if over_price > 1 and under_price > 1:
        for selection, probability, price in (
            ("over", probability_over, over_price),
            ("under", 1.0 - probability_over, under_price),
        ):
            if selection not in found:
                rows.append({
                    "market": "ou25", "selection": selection, "odds": round(price, 3),
                    "modelProb": round(probability, 4), "edge": round(probability * price - 1.0, 4),
                    "market_source": "The Odds API", "weather_adjusted": True,
                    "prediction_refreshed_at": source_stamp,
                })
    rows.sort(key=lambda row: float(row.get("edge", -99)), reverse=True)
    match["value"] = rows


def _apply_weather(match: dict, now_local: datetime) -> bool:
    weather = match.get("weather")
    if match.get("finished") or not isinstance(weather, dict):
        return False
    previous = match.get("weather_adjustment") if isinstance(match.get("weather_adjustment"), dict) else {}
    base_xg = _weather_base_xg(match, previous)
    if not base_xg:
        return False
    mult = weather_multipliers(weather)
    home = base_xg[0] * mult["goals"]
    away = base_xg[1] * mult["goals"]
    before = deepcopy({"xg": match.get("xg"), "stats": match.get("stats"), "markets": match.get("markets")})
    match["xg"] = [round(home, 2), round(away, 2)]

    stats = dict(match.get("stats") or {})
    old_mult = previous.get("multipliers") if isinstance(previous.get("multipliers"), dict) else {}
    mapping = {"goals": "goals", "shots": "shots", "sot": "shots", "fouls": "fouls", "yellows": "cards", "reds": "cards"}
    deltas = {}
    for key, factor_key in mapping.items():
        row = stats.get(key)
        if not isinstance(row, dict):
            continue
        previous_factor = _num(old_mult.get(factor_key), 1.0)
        base = _base_stat(row, previous_factor, bool(previous.get("applied")))
        if not base:
            continue
        if key == "goals":
            new_home, new_away = home, away
        else:
            factor = mult[factor_key]
            new_home, new_away = base[0] * factor, base[1] * factor
        stats[key] = {
            **row,
            "home": round(new_home, 2), "away": round(new_away, 2),
            "total": round(new_home + new_away, 2),
        }
        deltas[key] = {
            "before": round(base[0] + base[1], 2),
            "after": round(new_home + new_away, 2),
            "delta": round(new_home + new_away - base[0] - base[1], 2),
        }
    if stats:
        match["stats"] = stats

    total = home + away
    markets = dict(match.get("markets") or {})
    p_over = _over(total, 2.5)
    markets.update({
        "over_1_5": round(_over(total, 1.5), 3),
        "over_2_5": round(p_over, 3),
        "over_3_5": round(_over(total, 3.5), 3),
        "btts": round(_btts(home, away), 3),
    })
    match["markets"] = markets
    stamp = now_local.isoformat()
    _sync_ou_value(match, p_over, stamp)
    source_stamp = weather.get("source_updated_at") or weather.get("forecast_for")
    match["weather_adjustment"] = {
        "applied": bool(mult["reasons"]),
        "weather_source_updated_at": source_stamp,
        "weather_forecast_for": weather.get("forecast_for"),
        "weather_source": weather.get("source"),
        "weather_snapshot": {
            key: weather.get(key) for key in (
                "forecast_for", "temperature_c", "apparent_temperature_c", "humidity_pct",
                "precipitation_mm", "precipitation_probability_pct", "wind_kmh", "weather_code",
            ) if weather.get(key) is not None
        },
        "applied_at": stamp,
        "reason": "condiciones dentro de umbrales neutros" if not mult["reasons"] else None,
        "reasons": mult["reasons"],
        "multipliers": {key: mult[key] for key in ("goals", "shots", "fouls", "cards")},
        "xg": {
            "before": [round(base_xg[0], 2), round(base_xg[1], 2)],
            "after": [round(home, 2), round(away, 2)],
            "delta": [round(home - base_xg[0], 2), round(away - base_xg[1], 2)],
        },
        "stats": deltas,
        "one_x_two_adjusted": False,
        "method": "recálculo intradía conservador; 1X2 puro intacto hasta gate histórico",
    }
    after = {"xg": match.get("xg"), "stats": match.get("stats"), "markets": match.get("markets")}
    return before != after or previous.get("weather_source_updated_at") != source_stamp


def _lineup_side_impact(lineup: dict, side: str) -> dict:
    props = [row for row in lineup.get(f"clave_{side}") or [] if isinstance(row, dict)]
    availability = [row for row in lineup.get(f"disponibilidad_{side}") or [] if isinstance(row, dict)]
    minutes = [_num(row.get("min"), None) for row in props]
    minutes = [value for value in minutes if value is not None]
    starts = [_num(row.get("tit"), None) for row in props]
    starts = [value for value in starts if value is not None]
    attack_scores = []
    for row in props:
        try:
            minute_weight = min(1.0, max(0.0, float(row.get("min", 0))) / 90)
            start_weight = min(1.0, max(0.0, float(row.get("tit", 0))))
            production = 3 * float(row.get("g", 0)) + 2 * float(row.get("a", 0)) + float(row.get("r", 0)) + 1.5 * float(row.get("rp", 0))
            attack_scores.append(production * minute_weight * start_weight)
        except (TypeError, ValueError):
            continue
    absence_penalty = 0.0
    official_absences = 0
    for row in availability:
        state = str(row.get("estado") or "").casefold()
        official = bool(row.get("official"))
        official_absences += int(official)
        weight = 1.5 if "duda" in state or "doubt" in state else 2.0
        if "sanc" in state or "susp" in state or "les" in state or "injur" in state:
            weight = 3.0
        elif "rota" in state:
            weight = 1.0
        absence_penalty += weight if official else weight * .35
    return {
        "key_players": len(props),
        "expected_minutes_avg": round(sum(minutes) / len(minutes), 1) if minutes else None,
        "starter_probability_avg_pct": round(100 * sum(starts) / len(starts)) if starts else None,
        "attack_presence_index": round(sum(attack_scores), 2) if attack_scores else None,
        "listed_absences": len(availability),
        "official_absences": official_absences,
        "confidence_penalty_pp": round(min(12.0, absence_penalty), 1),
    }


def _update_confidence(match: dict, now_local: datetime) -> bool:
    probs = match.get("probs")
    if not isinstance(probs, list) or len(probs) != 3:
        return False
    before = deepcopy({
        "lineup_impact": match.get("lineup_impact"),
        "prediction_confidence": match.get("prediction_confidence"),
        "recommendation": match.get("recommendation"),
    })
    lineup = match.get("alineacion") if isinstance(match.get("alineacion"), dict) else {}
    home = _lineup_side_impact(lineup, "local")
    away = _lineup_side_impact(lineup, "visitante")
    status = lineup.get("status") or "estimado"
    status_penalty = {"confirmado": 0, "probable": 2, "estimado": 5}.get(status, 5)
    total_lineup_penalty = min(20.0, status_penalty + home["confidence_penalty_pp"] + away["confidence_penalty_pp"])
    attack_edge = None
    if home["attack_presence_index"] is not None and away["attack_presence_index"] is not None:
        attack_edge = round(home["attack_presence_index"] - away["attack_presence_index"], 2)
    match["lineup_impact"] = {
        "status": status,
        "evidence": "alta" if status == "confirmado" else "media" if status == "probable" else "baja",
        "home": home, "away": away,
        "attack_presence_edge": attack_edge,
        "confidence_penalty_pp": round(total_lineup_penalty, 1),
        "probability_adjustment": "not_applied",
        "method": "actualización intradía de minutos/producción/bajas; no altera 1X2 puro sin gate histórico",
    }

    old_conf = match.get("prediction_confidence") if isinstance(match.get("prediction_confidence"), dict) else {}
    disagreement = _num(old_conf.get("model_disagreement_pp"), 0.0)
    heat = ((match.get("weather") or {}).get("heat_stress") or {})
    penalty = min(20.0, total_lineup_penalty + (4 if heat.get("level") == "alto" else 0))
    score = max(0, min(100, round(max(float(value) for value in probs) + 35 - disagreement - penalty)))
    components = (match.get("model_meta") or {}).get("components") or {}
    evidence = {
        "probabilities": True,
        "model_agreement": bool(components) or bool((old_conf.get("evidence") or {}).get("model_agreement")),
        "form_and_splits": bool(match.get("tendencias")),
        "tactical_profile": bool(match.get("tactical_matchup")),
        "lineup": bool(lineup),
        "official_lineup": status == "confirmado",
        "weather": isinstance(match.get("weather"), dict),
        "market_odds": isinstance(match.get("odds"), dict),
    }
    weights = {
        "probabilities": 25, "model_agreement": 20, "form_and_splits": 15,
        "tactical_profile": 15, "lineup": 10, "official_lineup": 5,
        "weather": 5, "market_odds": 5,
    }
    completeness = sum(weights[key] for key, present in evidence.items() if present)
    match["prediction_confidence"] = {
        **old_conf,
        "score": score,
        "level": "alta" if score >= 72 else "media" if score >= 55 else "baja",
        "model_disagreement_pp": round(disagreement, 1),
        "availability_penalty_pp": round(penalty, 1),
        "data_completeness_pct": completeness,
        "evidence": evidence,
        "refreshed_at": now_local.isoformat(),
    }
    no_pick = []
    if score < 48:
        no_pick.append("confianza insuficiente")
    if disagreement >= 18:
        no_pick.append("desacuerdo alto entre modelos")
    if completeness < 55:
        no_pick.append("datos incompletos")
    match["recommendation"] = {
        "decision": "no_pick" if no_pick else "eligible",
        "label": "Sin apuesta recomendada" if no_pick else "Pronóstico publicable",
        "reasons": no_pick,
        "policy": "abstención automática por incertidumbre o falta de evidencia",
        "refreshed_at": now_local.isoformat(),
    }
    after = {
        "lineup_impact": match.get("lineup_impact"),
        "prediction_confidence": match.get("prediction_confidence"),
        "recommendation": match.get("recommendation"),
    }
    return before != after


def refresh_payload(payload: dict, now: datetime | None = None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    stats = {"matches": 0, "weather_recalculated": 0, "confidence_recalculated": 0}
    changed = False
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished"):
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        hours_to = (kickoff - now_local).total_seconds() / 3600
        if not -1 <= hours_to <= 18:
            continue
        stats["matches"] += 1
        if _apply_weather(match, now_local):
            stats["weather_recalculated"] += 1
            changed = True
        if _update_confidence(match, now_local):
            stats["confidence_recalculated"] += 1
            changed = True
        match["prediction_live_refresh"] = {
            "checked_at": now_local.isoformat(),
            "cadence_target_minutes": 5,
            "model_retrained": False,
            "pure_model_probs_changed": False,
            "reacts_to": ["weather", "lineup", "absences", "market"],
        }
        changed = True
    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, stats


def run(path=OUTPUT, now: datetime | None = None) -> tuple[bool, dict]:
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
