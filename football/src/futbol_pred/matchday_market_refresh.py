"""Refresco ligero de cuotas destacadas para partidos del día.

Objetivo: que la capa de mercado no espere al pipeline pesado cuando The Odds API
ya publicó una cuota nueva. Solo usa stdlib + requests para poder ejecutarse en
el hot-refresh de 5 minutos.

- consulta como máximo una vez por liga y pasada;
- adapta el TTL a la proximidad del kickoff y a los créditos restantes;
- actualiza 1X2/O-U 2.5 y la capa de value;
- conserva ``model_probs`` como probabilidad pura del modelo y solo recalibra
  ``probs`` cuando ya existe una política de calibración modelo↔mercado;
- persiste telemetría de cuota para no agotar el plan mensual.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import math
import os
import re
import unicodedata

import requests

from .feed_quality import load_feed, write_feed_safely
from .hot_refresh import MADRID, OUTPUT, _aware, _parse

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEYS = {
    "LaLiga": "soccer_spain_la_liga",
    "LaLiga Hypermotion": "soccer_spain_segunda_division",
    "Champions League": "soccer_uefa_champs_league",
}
SIGNS = ("1", "X", "2")


def _key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\b(fc|cf|cd|ud|club|deportivo|real)\b|[^a-z0-9]", "", text)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stamp(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _aware(parsed).astimezone(MADRID)


def _normalise(values: dict[str, float]) -> dict[str, float]:
    clean = {key: max(1e-9, float(values.get(key, 0.0))) for key in SIGNS}
    total = sum(clean.values()) or 1.0
    return {key: clean[key] / total for key in SIGNS}


def _remove_vig(prices: list[float]) -> list[float]:
    implied = [1.0 / float(price) for price in prices]
    total = sum(implied) or 1.0
    return [value / total for value in implied]


def _temperature_scale(probs: dict[str, float], temperature: float) -> dict[str, float]:
    temp = max(0.35, min(3.0, float(temperature or 1.0)))
    values = _normalise(probs)
    return _normalise({key: values[key] ** (1.0 / temp) for key in SIGNS})


def _base_ttl_minutes(hours_to_kickoff: float) -> int:
    """Máxima frescura útil antes del partido, sin consultar después del kickoff."""
    if hours_to_kickoff <= 0:
        return 10_000
    if hours_to_kickoff <= 1.5:
        return 5
    if hours_to_kickoff <= 3:
        return 10
    if hours_to_kickoff <= 6:
        return 20
    if hours_to_kickoff <= 12:
        return 30
    return 60


def ttl_minutes(hours_to_kickoff: float, remaining_credits: int | None = None) -> int:
    """TTL dinámico. Si el plan está cerca de agotarse, preserva cuota para T-90/T-30."""
    ttl = _base_ttl_minutes(hours_to_kickoff)
    if remaining_credits is None:
        return ttl
    if remaining_credits <= 20:
        return max(ttl, 90)
    if remaining_credits <= 80:
        return max(ttl, 60)
    if remaining_credits <= 200:
        return max(ttl, 30)
    # El Starter gratuito tiene 500 créditos/mes. Con <=500 ya somos prudentes:
    # 15 min cerca del kickoff en vez de gastar ~54 créditos por liga en 90 min.
    if remaining_credits <= 500:
        return max(ttl, 15)
    return ttl


def _age_minutes(now_local: datetime, value) -> float | None:
    stamp = _stamp(value)
    if stamp is None:
        return None
    return max(0.0, (now_local - stamp).total_seconds() / 60)


def _event_score(match: dict, event: dict) -> tuple[float, float]:
    mh, ma = _key(match.get("home")), _key(match.get("away"))
    eh, ea = _key(event.get("home_team")), _key(event.get("away_team"))
    if not mh or not ma or not eh or not ea:
        return 0.0, 999999.0
    score = (SequenceMatcher(None, mh, eh).ratio() + SequenceMatcher(None, ma, ea).ratio()) / 2
    kickoff = _parse(match.get("kickoff"))
    event_time = _stamp(event.get("commence_time"))
    gap = abs((kickoff - event_time).total_seconds()) if kickoff and event_time else 0.0
    return score, gap


def _match_event(match: dict, events: list[dict]) -> dict | None:
    best = None
    for event in events or []:
        score, gap = _event_score(match, event)
        if score < 0.72 or gap > 6 * 3600:
            continue
        candidate = (score, -gap, event)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None


def _latest_update(event: dict) -> str | None:
    values = []
    for book in event.get("bookmakers") or []:
        if book.get("last_update"):
            values.append(str(book["last_update"]))
        for market in book.get("markets") or []:
            if market.get("last_update"):
                values.append(str(market["last_update"]))
    return max(values) if values else None


def _event_market(event: dict) -> dict:
    home, away = str(event.get("home_team") or ""), str(event.get("away_team") or "")
    h2h = {"1": [], "X": [], "2": []}
    totals = {"over": [], "under": []}
    spreads = []
    for book in event.get("bookmakers") or []:
        bookmaker = str(book.get("title") or book.get("key") or "")
        for market in book.get("markets") or []:
            key = str(market.get("key") or "")
            for outcome in market.get("outcomes") or []:
                price = _num(outcome.get("price"))
                if price is None or price <= 1:
                    continue
                name = str(outcome.get("name") or "")
                if key == "h2h":
                    selection = "1" if _key(name) == _key(home) else "2" if _key(name) == _key(away) else "X" if name.casefold() == "draw" else None
                    if selection:
                        h2h[selection].append(price)
                elif key == "totals" and _num(outcome.get("point")) == 2.5:
                    selection = name.casefold()
                    if selection in totals:
                        totals[selection].append(price)
                elif key == "spreads" and _num(outcome.get("point")) is not None:
                    side = "home" if _key(name) == _key(home) else "away" if _key(name) == _key(away) else None
                    if side:
                        spreads.append({
                            "side": side,
                            "line": float(outcome["point"]),
                            "odds": round(price, 3),
                            "bookmaker": bookmaker,
                        })
    one = {key: round(sum(values) / len(values), 3) for key, values in h2h.items() if values}
    ou = {key: round(sum(values) / len(values), 3) for key, values in totals.items() if values}
    return {
        "1x2": one if len(one) == 3 else None,
        "ou25": ou if len(ou) == 2 else None,
        "spreads": spreads,
        "source_updated_at": _latest_update(event),
    }


def _movement(opening: dict | None, latest: dict) -> dict:
    out = {}
    for key in SIGNS:
        old = _num((opening or {}).get(key))
        new = _num(latest.get(key))
        if old and new:
            out[key] = round(100 * (new - old) / old, 1)
    return out


def _recalibrate_one_x_two(match: dict, latest: dict, fair: dict, stamp: str) -> None:
    model_probs = match.get("model_probs")
    calibration = match.get("market_calibration")
    if not isinstance(model_probs, list) or len(model_probs) != 3 or not isinstance(calibration, dict):
        return
    try:
        base = {"1": float(model_probs[0]) / 100, "X": float(model_probs[1]) / 100, "2": float(model_probs[2]) / 100}
        weight = max(0.0, min(1.0, float(calibration.get("model_weight", 0.6))))
        temperature = float(calibration.get("temperature", 1.0))
    except (TypeError, ValueError):
        return
    blended = {key: weight * base[key] + (1.0 - weight) * fair[key] for key in SIGNS}
    calibrated = _temperature_scale(blended, temperature)
    before = list(match.get("probs") or [])
    after = [round(calibrated["1"] * 100), round(calibrated["X"] * 100), round(calibrated["2"] * 100)]
    match["probs"] = after
    match["calibrated"] = True
    match["market_calibration"] = {
        **calibration,
        "live_market_source": "The Odds API",
        "live_market_updated_at": stamp,
    }
    match["market_live_recalibration"] = {
        "at": stamp,
        "before": before,
        "after": after,
        "latest_odds": latest,
        "policy": "model_probs inmutables + mercado sin vig + temperatura de producción",
    }


def _apply_market(match: dict, market: dict, now_local: datetime, ttl: int) -> bool:
    one = market.get("1x2")
    if not one:
        return False
    fair_values = _remove_vig([one["1"], one["X"], one["2"]])
    fair = {"1": fair_values[0], "X": fair_values[1], "2": fair_values[2]}
    stamp = now_local.isoformat()

    old_odds = match.get("odds") if isinstance(match.get("odds"), dict) else {}
    old_meta = old_odds.get("meta") if isinstance(old_odds.get("meta"), dict) else {}
    old_one = ((old_odds.get("1x2") or {}).get("odds") if isinstance(old_odds.get("1x2"), dict) else None)
    opening = old_meta.get("opening_1x2") or old_one or one
    meta = {
        **old_meta,
        "opening_1x2": opening,
        "latest_1x2": one,
        "movement_pct": _movement(opening, one),
        "movement_source": "the_odds_api_live",
        "provider": "The Odds API",
        "source_updated_at": market.get("source_updated_at") or stamp,
        "checked_at": stamp,
        "ttl_minutes": ttl,
    }
    block = {
        **old_odds,
        "1x2": {"odds": one, "fair": {key: round(fair[key], 4) for key in SIGNS}},
        "meta": meta,
    }

    ou = market.get("ou25")
    if ou:
        ou_fair_values = _remove_vig([ou["over"], ou["under"]])
        block["ou25"] = {
            "odds": ou,
            "fair": {"over": round(ou_fair_values[0], 4), "under": round(ou_fair_values[1], 4)},
        }
    if market.get("spreads"):
        block["spreads"] = market["spreads"]

    old_core = json.dumps(old_odds, sort_keys=True, default=str)
    new_core = json.dumps(block, sort_keys=True, default=str)
    match["odds"] = block

    _recalibrate_one_x_two(match, one, fair, stamp)

    preserved = [
        dict(row) for row in (match.get("value") or [])
        if isinstance(row, dict) and row.get("market") not in {"1x2", "ou25"}
    ]
    probs = match.get("probs") if isinstance(match.get("probs"), list) and len(match.get("probs")) == 3 else None
    if probs:
        for index, selection in enumerate(SIGNS):
            probability = float(probs[index]) / 100
            preserved.append({
                "market": "1x2", "selection": selection, "odds": round(float(one[selection]), 3),
                "modelProb": round(probability, 4),
                "edge": round(probability * float(one[selection]) - 1.0, 4),
                "market_source": "The Odds API", "source_updated_at": market.get("source_updated_at") or stamp,
            })
    if ou:
        model_over = _num((match.get("markets") or {}).get("over_2_5"))
        calibration = match.get("market_calibration") if isinstance(match.get("market_calibration"), dict) else {}
        if model_over is not None:
            fair_ou = _remove_vig([ou["over"], ou["under"]])
            weight = max(0.0, min(1.0, float(calibration.get("model_weight", 1.0))))
            calibrated_over = weight * model_over + (1.0 - weight) * fair_ou[0]
            for selection, probability in (("over", calibrated_over), ("under", 1.0 - calibrated_over)):
                preserved.append({
                    "market": "ou25", "selection": selection, "odds": round(float(ou[selection]), 3),
                    "modelProb": round(probability, 4),
                    "edge": round(probability * float(ou[selection]) - 1.0, 4),
                    "market_source": "The Odds API", "source_updated_at": market.get("source_updated_at") or stamp,
                })
    preserved.sort(key=lambda row: float(row.get("edge", -99)), reverse=True)
    match["value"] = preserved
    match["market_hot_refresh"] = {
        "checked_at": stamp,
        "captured_at": stamp,
        "source_updated_at": market.get("source_updated_at") or stamp,
        "ttl_minutes": ttl,
        "provider": "The Odds API",
    }
    if old_core != new_core:
        match["updatedAt"] = stamp
        return True
    return True  # el check/TTL también es información operativa nueva


class OddsHotClient:
    def __init__(self, api_key: str | None = None, timeout: int = 15, session=requests):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")
        self.timeout = timeout
        self.session = session
        self.quota = {"remaining": None, "used": None, "last_cost": None}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def featured(self, league_label: str) -> list[dict]:
        sport = SPORT_KEYS.get(league_label)
        if not self.available or not sport:
            return []
        response = self.session.get(
            f"{BASE_URL}/sports/{sport}/odds",
            params={
                "apiKey": self.api_key,
                "regions": "eu",
                "markets": "h2h,totals,spreads",
                "oddsFormat": "decimal",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        headers = {str(key).lower(): value for key, value in getattr(response, "headers", {}).items()}
        for key, header in (("remaining", "x-requests-remaining"), ("used", "x-requests-used"), ("last_cost", "x-requests-last")):
            try:
                self.quota[key] = int(headers.get(header))
            except (TypeError, ValueError):
                pass
        data = response.json()
        return data if isinstance(data, list) else []


def refresh_payload(payload: dict, now: datetime | None = None, client: OddsHotClient | None = None) -> tuple[bool, dict]:
    now_local = _aware(now or datetime.now(timezone.utc)).astimezone(MADRID)
    client = client or OddsHotClient()
    if not client.available:
        return False, {"available": False, "refreshed": 0, "leagues_queried": 0}

    previous_health = ((payload.get("source_health") or {}).get("the_odds_api") or {})
    try:
        previous_remaining = int(previous_health.get("remaining"))
    except (TypeError, ValueError):
        previous_remaining = None
    if previous_remaining is not None and previous_remaining <= 5:
        return False, {"available": True, "refreshed": 0, "leagues_queried": 0, "quota_guard": "exhausted"}

    due_by_league: dict[str, list[tuple[dict, int]]] = {}
    for match in payload.get("matches") or []:
        if not isinstance(match, dict) or match.get("finished") or match.get("league") not in SPORT_KEYS:
            continue
        kickoff = _parse(match.get("kickoff"))
        if not kickoff or kickoff.date() != now_local.date():
            continue
        hours_to = (kickoff - now_local).total_seconds() / 3600
        if hours_to <= 0 or hours_to > 18:
            continue
        ttl = ttl_minutes(hours_to, previous_remaining)
        last = ((match.get("market_hot_refresh") or {}).get("captured_at")
                or (((match.get("odds") or {}).get("meta") or {}).get("checked_at") if isinstance(match.get("odds"), dict) else None))
        age = _age_minutes(now_local, last)
        if age is None or age >= ttl:
            due_by_league.setdefault(match["league"], []).append((match, ttl))

    changed = False
    refreshed = queried = 0
    errors = []
    for league, rows in sorted(due_by_league.items()):
        if client.quota.get("remaining") is not None and client.quota["remaining"] <= 5:
            break
        try:
            events = client.featured(league)
            queried += 1
        except requests.RequestException as exc:
            errors.append(f"{league}: {type(exc).__name__}")
            continue
        for match, ttl in rows:
            event = _match_event(match, events)
            if not event:
                continue
            market = _event_market(event)
            if _apply_market(match, market, now_local, ttl):
                changed = True
                refreshed += 1

    if queried:
        health = dict(payload.get("source_health") or {})
        health["the_odds_api"] = {
            **client.quota,
            "checked_at": now_local.isoformat(),
            "policy": "TTL dinámico por kickoff y créditos restantes",
        }
        payload["source_health"] = health
        changed = True
    if changed:
        payload["generated_at"] = now_local.isoformat()
    return changed, {
        "available": True,
        "refreshed": refreshed,
        "leagues_queried": queried,
        "quota": dict(client.quota),
        "errors": errors,
    }


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
