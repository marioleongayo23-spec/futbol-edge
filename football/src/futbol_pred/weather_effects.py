"""Ajuste meteorológico explícito sobre expectativas, nunca sobre 1X2 sin gate.

Los multiplicadores son conservadores y acotados. El bloque conserva el valor
base y el delta para que la UI explique exactamente qué cambió. Si el mismo
forecast ya fue aplicado sobre el mismo xG, la función es idempotente; si un
cron reconstruye el xG base, el ajuste se reaplica aunque la previsión no cambie.
"""
from __future__ import annotations

import math
from datetime import datetime

from scipy.stats import poisson


def _num(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _same_pair(left, right, tolerance: float = 0.015) -> bool:
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
        goals *= 0.92; shots *= 0.92; fouls *= 1.03; cards *= 1.04
        reasons.append(f"viento fuerte {wind:.0f} km/h")
    elif wind >= 25:
        goals *= 0.96; shots *= 0.96; fouls *= 1.02; cards *= 1.03
        reasons.append(f"viento {wind:.0f} km/h")

    if rain >= 4.0:
        goals *= 0.94; shots *= 0.95; fouls *= 1.05; cards *= 1.06
        reasons.append(f"lluvia fuerte {rain:.1f} mm/h")
    elif rain >= 1.5 or rain_prob >= 75:
        goals *= 0.97; shots *= 0.97; fouls *= 1.03; cards *= 1.04
        reasons.append("lluvia probable/intensa")

    if apparent >= 34:
        goals *= 0.98; shots *= 0.97; fouls *= 1.02
        reasons.append(f"estrés térmico {apparent:.0f} °C aparente")

    # Límites para que una heurística contextual nunca domine al modelo base.
    return {
        "goals": round(max(0.88, min(1.02, goals)), 4),
        "shots": round(max(0.88, min(1.02, shots)), 4),
        "fouls": round(max(0.98, min(1.10, fouls)), 4),
        "cards": round(max(0.98, min(1.12, cards)), 4),
        "reasons": reasons,
    }


def _over(total_mean: float, line: float) -> float:
    return float(1.0 - poisson.cdf(math.floor(line), max(0.0, total_mean)))


def _btts(home: float, away: float) -> float:
    return 1.0 - math.exp(-home) - math.exp(-away) + math.exp(-(home + away))


def _scaled_stat(stats: dict, key: str, multiplier: float) -> dict | None:
    row = stats.get(key)
    if not isinstance(row, dict):
        return None
    try:
        home, away = float(row["home"]), float(row["away"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        **row,
        "home": round(home * multiplier, 2),
        "away": round(away * multiplier, 2),
        "total": round((home + away) * multiplier, 2),
    }


def apply_weather_adjustment(match: dict, now: datetime | None = None) -> bool:
    if match.get("finished") or not isinstance(match.get("weather"), dict):
        return False
    xg = match.get("xg")
    if not isinstance(xg, list) or len(xg) != 2:
        return False
    weather = match["weather"]
    source_stamp = weather.get("source_updated_at") or weather.get("forecast_for")
    previous = match.get("weather_adjustment") or {}
    # El dashboard se reconstruye desde el modelo en cada cron. Por eso "mismo
    # forecast" no implica que el xG actual ya esté ajustado: solo saltamos si
    # el xG coincide con el AFTER previamente publicado. Si ha vuelto al base,
    # reaplicamos el multiplicador y mantenemos coherencia entre metadata y datos.
    if (
        previous.get("weather_source_updated_at") == source_stamp
        and previous.get("applied")
        and _same_pair(xg, (previous.get("xg") or {}).get("after"))
    ):
        return False

    mult = weather_multipliers(weather)
    if not mult["reasons"]:
        match["weather_adjustment"] = {
            "applied": False,
            "weather_source_updated_at": source_stamp,
            "reason": "condiciones dentro de umbrales neutros",
            "multipliers": {k: mult[k] for k in ("goals", "shots", "fouls", "cards")},
            "one_x_two_adjusted": False,
        }
        return False

    base_home, base_away = float(xg[0]), float(xg[1])
    adj_home, adj_away = base_home * mult["goals"], base_away * mult["goals"]
    match["xg"] = [round(adj_home, 2), round(adj_away, 2)]

    stats = dict(match.get("stats") or {})
    mapping = {
        "goals": mult["goals"], "shots": mult["shots"], "sot": mult["shots"],
        "fouls": mult["fouls"], "yellows": mult["cards"], "reds": mult["cards"],
    }
    stat_deltas = {}
    for key, factor in mapping.items():
        old = stats.get(key)
        new = _scaled_stat(stats, key, factor)
        if new:
            stats[key] = new
            stat_deltas[key] = {
                "before": round(float(old.get("total", 0)), 2),
                "after": new["total"],
                "delta": round(new["total"] - float(old.get("total", 0)), 2),
            }
    if stats:
        match["stats"] = stats

    markets = dict(match.get("markets") or {})
    total = adj_home + adj_away
    markets.update({
        "over_1_5": round(_over(total, 1.5), 3),
        "over_2_5": round(_over(total, 2.5), 3),
        "over_3_5": round(_over(total, 3.5), 3),
        "btts": round(_btts(adj_home, adj_away), 3),
    })
    match["markets"] = markets
    match["weather_adjustment"] = {
        "applied": True,
        "weather_source_updated_at": source_stamp,
        "applied_at": (now.isoformat() if now else None),
        "reasons": mult["reasons"],
        "multipliers": {k: mult[k] for k in ("goals", "shots", "fouls", "cards")},
        "xg": {
            "before": [round(base_home, 2), round(base_away, 2)],
            "after": [round(adj_home, 2), round(adj_away, 2)],
            "delta": [round(adj_home - base_home, 2), round(adj_away - base_away, 2)],
        },
        "stats": stat_deltas,
        "one_x_two_adjusted": False,
        "method": "heurística meteorológica conservadora y acotada; 1X2 intacto hasta validación histórica",
    }
    return True


def apply_weather_adjustments(matches: list[dict], now: datetime | None = None) -> int:
    return sum(int(apply_weather_adjustment(match, now)) for match in matches)
