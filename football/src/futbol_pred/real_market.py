"""Cuotas reales, snapshot T-2h y value multi-mercado.

The Odds API es la fuente preferida cuando existe ``ODDS_API_KEY``. Los mercados
no featured se consultan por evento y con TTL/presupuesto acotado. Sin clave se
usa football-data.co.uk únicamente para los mercados que realmente publica.
Nunca se fabrican cuotas ni se reciclan datos sample para CLV/value.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import math
import re
import unicodedata

import requests
from scipy.stats import poisson

from .config import settings
from .ingest.football_data_uk import DIV_CODE, FootballDataUKClient

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEYS = {
    "LaLiga": "soccer_spain_la_liga",
    "LaLiga Hypermotion": "soccer_spain_segunda_division",
    "Champions League": "soccer_uefa_champs_league",
}
EXTRA_MARKETS = (
    "btts", "alternate_totals_corners", "alternate_totals_cards", "alternate_spreads",
)
PLAYER_MARKETS = ("player_shots", "player_shots_on_target", "player_to_receive_card")


def _key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\b(fc|cf|cd|ud|club|deportivo)\b|[^a-z0-9]", "", text)


def _dt(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.astimezone()
    except (TypeError, ValueError):
        return None


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class Quote:
    event_id: str
    home: str
    away: str
    market: str
    bookmaker: str
    selection: str
    odds: float
    point: float | None = None
    player: str | None = None
    updated_at: str | None = None


class RealOddsClient:
    """Cliente deliberadamente sin modo sample: sin clave devuelve vacío."""

    def __init__(self, api_key: str | None = None, timeout: int = 16, session=requests):
        self.api_key = api_key or settings.odds_api_key
        self.timeout = timeout
        self.session = session
        self._events: dict[str, list[dict]] = {}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: dict) -> object:
        if not self.available:
            return []
        response = self.session.get(
            f"{BASE_URL}/{path.lstrip('/')}",
            params={"apiKey": self.api_key, **params},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def events(self, league_label: str) -> list[dict]:
        sport = SPORT_KEYS.get(league_label)
        if not sport or not self.available:
            return []
        if sport not in self._events:
            try:
                data = self._get(f"sports/{sport}/events", {})
                self._events[sport] = data if isinstance(data, list) else []
            except requests.RequestException:
                self._events[sport] = []
        return self._events[sport]

    def featured(self, league_label: str) -> list[Quote]:
        sport = SPORT_KEYS.get(league_label)
        if not sport or not self.available:
            return []
        try:
            data = self._get(
                f"sports/{sport}/odds",
                {"regions": "eu", "markets": "h2h,totals,spreads", "oddsFormat": "decimal"},
            )
        except requests.RequestException:
            return []
        return _normalise_response(data)

    def event_odds(self, league_label: str, event_id: str, *, player_props: bool = False) -> list[Quote]:
        sport = SPORT_KEYS.get(league_label)
        if not sport or not self.available or not event_id:
            return []
        markets = PLAYER_MARKETS if player_props else EXTRA_MARKETS
        # Los props de fútbol están documentados principalmente para books US.
        regions = "us" if player_props else "eu"
        try:
            data = self._get(
                f"sports/{sport}/events/{event_id}/odds",
                {"regions": regions, "markets": ",".join(markets), "oddsFormat": "decimal"},
            )
        except requests.RequestException:
            return []
        return _normalise_response([data] if isinstance(data, dict) else data)


def _normalise_response(data) -> list[Quote]:
    rows: list[Quote] = []
    for event in data or []:
        event_id = str(event.get("id") or "")
        home, away = str(event.get("home_team") or ""), str(event.get("away_team") or "")
        if not event_id or not home or not away:
            continue
        for book in event.get("bookmakers") or []:
            bookmaker = str(book.get("title") or book.get("key") or "")
            for market in book.get("markets") or []:
                mkey = str(market.get("key") or "")
                updated = market.get("last_update") or book.get("last_update")
                for outcome in market.get("outcomes") or []:
                    price = _num(outcome.get("price"))
                    if not price or price <= 1:
                        continue
                    rows.append(Quote(
                        event_id=event_id, home=home, away=away, market=mkey,
                        bookmaker=bookmaker, selection=str(outcome.get("name") or ""),
                        odds=price, point=_num(outcome.get("point")),
                        player=str(outcome.get("description") or "").strip() or None,
                        updated_at=str(updated) if updated else None,
                    ))
    return rows


def _match_event(match: dict, events: list[dict]) -> str | None:
    home, away = _key(match.get("home")), _key(match.get("away"))
    kickoff = _dt(match.get("kickoff"))
    best = None
    for event in events:
        eh, ea = _key(event.get("home_team")), _key(event.get("away_team"))
        if not home or not away or not eh or not ea:
            continue
        name_score = int(home == eh) + int(away == ea)
        if name_score < 2:
            continue
        event_time = _dt(event.get("commence_time"))
        gap = abs((event_time - kickoff).total_seconds()) if event_time and kickoff else 0
        if gap > 6 * 3600:
            continue
        candidate = (gap, str(event.get("id") or ""))
        if candidate[1] and (best is None or candidate < best):
            best = candidate
    return best[1] if best else None


def _quotes_for_match(match: dict, quotes: list[Quote]) -> list[Quote]:
    home, away = _key(match.get("home")), _key(match.get("away"))
    return [q for q in quotes if _key(q.home) == home and _key(q.away) == away]


def _consensus(prices: list[float]) -> float | None:
    clean = [float(v) for v in prices if v and v > 1]
    return round(sum(clean) / len(clean), 3) if clean else None


def _featured_block(match: dict, quotes: list[Quote]) -> dict:
    rows = _quotes_for_match(match, quotes)
    home, away = match.get("home"), match.get("away")
    h2h: dict[str, list[float]] = defaultdict(list)
    totals: dict[tuple[str, float], list[float]] = defaultdict(list)
    spreads: list[dict] = []
    for q in rows:
        if q.market == "h2h":
            sel = "1" if _key(q.selection) == _key(home) else "2" if _key(q.selection) == _key(away) else "X" if q.selection.casefold() == "draw" else None
            if sel:
                h2h[sel].append(q.odds)
        elif q.market == "totals" and q.point is not None:
            totals[(q.selection.casefold(), q.point)].append(q.odds)
        elif q.market in {"spreads", "alternate_spreads"} and q.point is not None:
            side = "home" if _key(q.selection) == _key(home) else "away" if _key(q.selection) == _key(away) else None
            if side:
                spreads.append({"side": side, "line": q.point, "odds": q.odds, "bookmaker": q.bookmaker})
    out: dict = {}
    if all(h2h.get(key) for key in ("1", "X", "2")):
        out["1x2"] = {key: _consensus(h2h[key]) for key in ("1", "X", "2")}
        out["1x2_books"] = min(len(h2h[key]) for key in ("1", "X", "2"))
    if totals.get(("over", 2.5)) and totals.get(("under", 2.5)):
        out["ou25"] = {
            "over": _consensus(totals[("over", 2.5)]),
            "under": _consensus(totals[("under", 2.5)]),
        }
        out["ou25_books"] = min(len(totals[("over", 2.5)]), len(totals[("under", 2.5)]))
    if spreads:
        out["spreads"] = spreads
    return out


def _co_uk_featured(match: dict, cache: dict[str, list[dict]]) -> dict:
    label = match.get("league")
    league = "laliga" if label == "LaLiga" else "segunda" if label == "LaLiga Hypermotion" else None
    if not league:
        return {}
    if league not in cache:
        cache[league] = FootballDataUKClient().get_odds(DIV_CODE[league])
    home, away = _key(match.get("home")), _key(match.get("away"))
    row = next((r for r in cache[league] if _key(r.get("home")) == home and _key(r.get("away")) == away), None)
    return dict((row or {}).get("odds") or {})


def _previous_by_id(previous_matches: list[dict] | None) -> dict[str, dict]:
    return {str(m.get("id")): m for m in (previous_matches or []) if isinstance(m, dict) and m.get("id")}


def attach_closing_snapshots(
    matches: list[dict], now: datetime, *, previous_matches: list[dict] | None = None,
    client: RealOddsClient | None = None, window_minutes: tuple[int, int] = (90, 150),
) -> int:
    """Congela consenso 1X2 y O/U2.5 alrededor de T-2h, una sola vez."""
    client = client or RealOddsClient()
    prev = _previous_by_id(previous_matches)
    featured_cache: dict[str, list[Quote]] = {}
    co_cache: dict[str, list[dict]] = {}
    updated = 0
    low, high = sorted(window_minutes)
    for match in matches:
        old = prev.get(str(match.get("id"))) or {}
        old_close = old.get("closing_odds")
        if isinstance(old_close, dict) and old_close.get("capture_kind") == "t_minus_2h":
            match["closing_odds"] = old_close
            continue
        if match.get("finished"):
            closing = match.get("closing_odds")
            if isinstance(closing, dict) and closing.get("1x2"):
                closing.setdefault("is_real", True)
                closing.setdefault("capture_kind", "historical_provider_close")
            continue
        kickoff = _dt(match.get("kickoff"))
        if not kickoff:
            continue
        minutes = (kickoff - now).total_seconds() / 60
        if minutes < low or minutes > high:
            continue
        block = {}
        label = match.get("league")
        if client.available and label in SPORT_KEYS:
            if label not in featured_cache:
                featured_cache[label] = client.featured(label)
            block = _featured_block(match, featured_cache[label])
        if not block.get("1x2"):
            block = _co_uk_featured(match, co_cache)
        one = block.get("1x2")
        ou = block.get("ou25")
        if not one or not all(_num(one.get(k)) and one[k] > 1 for k in ("1", "X", "2")):
            continue
        source = "The Odds API consensus" if client.available and label in featured_cache and _featured_block(match, featured_cache[label]).get("1x2") else "football-data.co.uk"
        close = {
            "1x2": {k: round(float(one[k]), 3) for k in ("1", "X", "2")},
            "market_source": source,
            "captured_at": now.isoformat(),
            "minutes_to_kickoff": round(minutes, 1),
            "capture_kind": "t_minus_2h",
            "is_real": True,
        }
        if ou and ou.get("over") and ou.get("under"):
            close["ou25"] = {"over": round(float(ou["over"]), 3), "under": round(float(ou["under"]), 3)}
        match["closing_odds"] = close
        updated += 1
    return updated


def _poisson_over(mean: float, line: float) -> float:
    if mean <= 0:
        return 0.0
    return float(1.0 - poisson.cdf(math.floor(line), mean))


def _score_grid(xg: list[float], max_goals: int = 10) -> list[tuple[int, int, float]]:
    if not isinstance(xg, list) or len(xg) != 2:
        return []
    lh, la = _num(xg[0]), _num(xg[1])
    if lh is None or la is None or lh <= 0 or la <= 0:
        return []
    return [(h, a, float(poisson.pmf(h, lh) * poisson.pmf(a, la))) for h in range(max_goals + 1) for a in range(max_goals + 1)]


def _asian_ev_prob(xg: list[float], side: str, line: float) -> tuple[float, float, float] | None:
    grid = _score_grid(xg)
    if not grid:
        return None
    win = push = loss = 0.0
    sign = 1 if side == "home" else -1
    for h, a, p in grid:
        margin = sign * (h - a) + float(line)
        if margin > 1e-9:
            win += p
        elif margin < -1e-9:
            loss += p
        else:
            push += p
    total = win + push + loss
    return (win / total, push / total, loss / total) if total else None


def _player_prop(match: dict, player: str) -> dict | None:
    lineup = match.get("alineacion") or {}
    for row in (lineup.get("clave_local") or []) + (lineup.get("clave_visitante") or []):
        if _key(row.get("jugador")) == _key(player) and str(row.get("source") or "").startswith("API-Football"):
            return row
    return None


def _extra_value_rows(match: dict, quotes: list[Quote], stats_model=None) -> list[dict]:
    out: list[dict] = []
    stats = match.get("stats") or {}
    for q in quotes:
        model_prob = None
        edge = None
        selection = q.selection
        if q.market == "btts":
            p_yes = _num((match.get("markets") or {}).get("btts"))
            if p_yes is not None:
                model_prob = p_yes if selection.casefold() in {"yes", "si", "sí"} else 1 - p_yes if selection.casefold() == "no" else None
        elif q.market in {"alternate_totals_corners", "alternate_totals_cards"} and q.point is not None:
            key = "corners" if "corners" in q.market else "yellows"
            expected = _num((stats.get(key) or {}).get("total"))
            if expected is not None:
                if stats_model is not None:
                    try:
                        over = stats_model.prob_over(expected, q.point, stats_model.dispersion(key))
                    except Exception:
                        over = _poisson_over(expected, q.point)
                else:
                    over = _poisson_over(expected, q.point)
                model_prob = over if selection.casefold() == "over" else 1 - over if selection.casefold() == "under" else None
        elif q.market in {"spreads", "alternate_spreads"} and q.point is not None:
            side = "home" if _key(selection) == _key(match.get("home")) else "away" if _key(selection) == _key(match.get("away")) else None
            probs = _asian_ev_prob(match.get("xg"), side, q.point) if side else None
            if probs:
                pwin, ppush, _ = probs
                model_prob = pwin
                edge = pwin * q.odds + ppush - 1.0
        elif q.market in PLAYER_MARKETS and q.player:
            prop = _player_prop(match, q.player)
            if prop:
                if q.market == "player_shots":
                    mean = _num(prop.get("r"))
                elif q.market == "player_shots_on_target":
                    mean = _num(prop.get("rp"))
                else:
                    mean = _num(prop.get("t"))
                if mean is not None:
                    if q.market == "player_to_receive_card":
                        yes = 1.0 - math.exp(-max(0.0, mean))
                        model_prob = yes if selection.casefold() in {"yes", "over"} else 1 - yes if selection.casefold() in {"no", "under"} else None
                    elif q.point is not None:
                        over = _poisson_over(mean, q.point)
                        model_prob = over if selection.casefold() == "over" else 1 - over if selection.casefold() == "under" else None
        if model_prob is None:
            continue
        if edge is None:
            edge = model_prob * q.odds - 1.0
        out.append({
            "market": q.market, "selection": selection, "line": q.point,
            "player": q.player, "bookmaker": q.bookmaker, "odds": round(q.odds, 3),
            "modelProb": round(model_prob, 4), "edge": round(edge, 4),
            "market_source": "The Odds API", "source_updated_at": q.updated_at,
        })
    return out


def attach_extended_market_value(
    matches: list[dict], now: datetime, *, previous_matches: list[dict] | None = None,
    stats_models: dict[str, object] | None = None, client: RealOddsClient | None = None,
    ttl_hours: float = 2.0, max_event_requests: int = 8,
) -> dict:
    """Añade mercados secundarios reales y ranking value sin fabricar cobertura."""
    client = client or RealOddsClient()
    prev = _previous_by_id(previous_matches)
    refreshed = 0
    global_rows: list[dict] = []
    requests_left = max(0, int(max_event_requests))
    if not client.available:
        return {"refreshed": 0, "ranking": [], "source": "football-data.co.uk fallback: sin submercados fiables"}
    for match in matches:
        if match.get("finished"):
            continue
        old = prev.get(str(match.get("id"))) or {}
        old_market = old.get("extended_market")
        stamp = _dt((old_market or {}).get("captured_at"))
        age = (now - stamp).total_seconds() / 3600 if stamp else None
        kickoff = _dt(match.get("kickoff"))
        hours_to = (kickoff - now).total_seconds() / 3600 if kickoff else 999
        if isinstance(old_market, dict) and age is not None and age < ttl_hours:
            match["extended_market"] = old_market
            rows = list(old.get("extended_value") or [])
            match["extended_value"] = rows
        elif requests_left > 0 and -1 <= hours_to <= 36 and match.get("league") in SPORT_KEYS:
            event_id = _match_event(match, client.events(match.get("league")))
            if event_id:
                quotes = client.event_odds(match.get("league"), event_id, player_props=False)
                requests_left -= 1
                if 0 <= hours_to <= 12 and requests_left > 0 and match.get("league") == "LaLiga":
                    quotes += client.event_odds(match.get("league"), event_id, player_props=True)
                    requests_left -= 1
                stats_model = (stats_models or {}).get(match.get("league"))
                rows = _extra_value_rows(match, quotes, stats_model)
                match["extended_market"] = {
                    "provider": "The Odds API", "event_id": event_id,
                    "captured_at": now.isoformat(), "real": True,
                    "markets": sorted({q.market for q in quotes}),
                }
                match["extended_value"] = sorted(rows, key=lambda row: row["edge"], reverse=True)
                refreshed += 1
        for row in (match.get("value") or []) + (match.get("extended_value") or []):
            try:
                edge = float(row.get("edge"))
            except (TypeError, ValueError):
                continue
            if edge <= 0.02 or match.get("recommendation", {}).get("decision") == "no_pick":
                continue
            global_rows.append({
                **row, "match_id": match.get("id"), "home": match.get("home"),
                "away": match.get("away"), "league": match.get("league"),
                "kickoff": match.get("kickoff"),
            })
    # Deduplica por partido/mercado/selección/línea/jugador conservando la mejor cuota.
    best = {}
    for row in global_rows:
        key = (row.get("match_id"), row.get("market"), row.get("selection"), row.get("line"), row.get("player"))
        if key not in best or float(row.get("edge", -99)) > float(best[key].get("edge", -99)):
            best[key] = row
    ranking = sorted(best.values(), key=lambda row: float(row.get("edge", -99)), reverse=True)[:40]
    return {"refreshed": refreshed, "ranking": ranking, "source": "The Odds API + co.uk featured fallback"}
