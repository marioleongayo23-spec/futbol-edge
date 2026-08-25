"""Cliente de The Odds API para cuotas de múltiples casas y submercados.

Docs: https://the-odds-api.com/liveapi/guides/v4/

Las cuotas generales mantienen un sample offline para desarrollo. Las props de
jugador, en cambio, fallan cerrado: sin API key o sin cobertura real devuelven
una lista vacía y nunca generan una cuota ficticia.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from ..config import settings

BASE_URL = "https://api.the-odds-api.com/v4"

# Mapeo de nuestras ligas a claves de The Odds API.
SPORT_KEYS = {
    "laliga": "soccer_spain_la_liga",
    "segunda": "soccer_spain_segunda_division",
    "champions": "soccer_uefa_champs_league",
}

# The Odds API documenta actualmente props de fútbol para LaLiga, entre otras
# ligas grandes, con cobertura principalmente de bookmakers de EE. UU. Segunda
# y Champions quedan fail-closed hasta confirmar cobertura del proveedor.
PLAYER_PROP_SUPPORTED_LEAGUES = {"laliga"}
PLAYER_PROP_MARKETS = (
    "player_shots",
    "player_shots_on_target",
    "player_to_receive_card",
    "player_assists",
)
PLAYER_PROP_METRICS = {
    "player_shots": "r",
    "player_shots_on_target": "rp",
    "player_to_receive_card": "t",
    "player_assists": "a",
}


@dataclass
class MarketOdds:
    home_team: str
    away_team: str
    market: str            # 1x2 / totals / spreads
    bookmaker: str
    selection: str
    odds: float
    point: float | None = None  # línea (para totals/spreads)


@dataclass
class PlayerPropOdds:
    event_id: str
    home_team: str
    away_team: str
    player: str
    metric: str
    market: str
    bookmaker: str
    bookmaker_title: str
    side: str               # over / under; Yes/No de tarjeta se normaliza a O/U
    odds: float
    point: float
    last_update: str | None = None


def _decimal(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 1 else None


def _point(market: str, value) -> float | None:
    if market == "player_to_receive_card" and value is None:
        return 0.5
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _side(market: str, value) -> str | None:
    name = str(value or "").strip().casefold()
    if market == "player_to_receive_card":
        return {"yes": "over", "no": "under"}.get(name)
    return name if name in {"over", "under"} else None


class OddsApiClient:
    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or settings.odds_api_key
        self.timeout = timeout

    @property
    def offline(self) -> bool:
        return not self.api_key

    def get_odds(
        self,
        league: str,
        markets: str = "h2h,totals,spreads",
        regions: str = "eu",
    ) -> list[MarketOdds]:
        if self.offline:
            return _sample_odds()

        sport = SPORT_KEYS[league]
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
        }
        resp = requests.get(
            f"{BASE_URL}/sports/{sport}/odds", params=params, timeout=self.timeout
        )
        resp.raise_for_status()
        out: list[MarketOdds] = []
        for event in resp.json():
            home = event["home_team"]
            away = event["away_team"]
            for bk in event.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for oc in mk.get("outcomes", []):
                        out.append(
                            MarketOdds(
                                home_team=home,
                                away_team=away,
                                market=mk["key"],
                                bookmaker=bk["key"],
                                selection=oc["name"],
                                odds=oc["price"],
                                point=oc.get("point"),
                            )
                        )
        return out

    def get_events(self, league: str) -> list[dict]:
        """Eventos actuales sin consumir cuota del proveedor.

        Se usa para resolver el ``event_id`` requerido por los mercados de props.
        """
        if self.offline or league not in PLAYER_PROP_SUPPORTED_LEAGUES:
            return []
        sport = SPORT_KEYS[league]
        response = requests.get(
            f"{BASE_URL}/sports/{sport}/events",
            params={"apiKey": self.api_key, "dateFormat": "iso"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        out = []
        for event in response.json() or []:
            event_id = str(event.get("id") or "").strip()
            home = str(event.get("home_team") or "").strip()
            away = str(event.get("away_team") or "").strip()
            if event_id and home and away:
                out.append({
                    "id": event_id,
                    "home_team": home,
                    "away_team": away,
                    "commence_time": event.get("commence_time"),
                })
        return out

    def get_player_props(
        self,
        league: str,
        event_id: str,
        markets: tuple[str, ...] | list[str] = PLAYER_PROP_MARKETS,
        regions: str = "us",
    ) -> list[PlayerPropOdds]:
        """Cuotas reales de props de un evento, normalizadas al modelo interno.

        Solo devuelve mercados documentados por el proveedor y outcomes con
        jugador, lado, línea y cuota decimal válidos. No hay sample offline.
        """
        if (
            self.offline
            or league not in PLAYER_PROP_SUPPORTED_LEAGUES
            or not str(event_id).strip()
        ):
            return []

        allowed = [market for market in markets if market in PLAYER_PROP_METRICS]
        if not allowed:
            return []
        sport = SPORT_KEYS[league]
        response = requests.get(
            f"{BASE_URL}/sports/{sport}/events/{event_id}/odds",
            params={
                "apiKey": self.api_key,
                "regions": regions,
                "markets": ",".join(allowed),
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        event = response.json() or {}
        out: list[PlayerPropOdds] = []
        for bookmaker in event.get("bookmakers", []) or []:
            bookmaker_key = str(bookmaker.get("key") or "").strip()
            bookmaker_title = str(bookmaker.get("title") or bookmaker_key).strip()
            if not bookmaker_key:
                continue
            for market in bookmaker.get("markets", []) or []:
                market_key = market.get("key")
                metric = PLAYER_PROP_METRICS.get(market_key)
                if not metric:
                    continue
                last_update = market.get("last_update")
                for outcome in market.get("outcomes", []) or []:
                    player = str(outcome.get("description") or "").strip()
                    side = _side(market_key, outcome.get("name"))
                    point = _point(market_key, outcome.get("point"))
                    price = _decimal(outcome.get("price"))
                    if not player or side is None or point is None or price is None:
                        continue
                    out.append(PlayerPropOdds(
                        event_id=str(event.get("id") or event_id),
                        home_team=str(event.get("home_team") or ""),
                        away_team=str(event.get("away_team") or ""),
                        player=player,
                        metric=metric,
                        market=market_key,
                        bookmaker=bookmaker_key,
                        bookmaker_title=bookmaker_title,
                        side=side,
                        odds=price,
                        point=point,
                        last_update=last_update,
                    ))
        return out


def _sample_odds() -> list[MarketOdds]:
    return [
        MarketOdds("Real Madrid", "Barcelona", "h2h", "sample", "Real Madrid", 2.10),
        MarketOdds("Real Madrid", "Barcelona", "h2h", "sample", "Draw", 3.60),
        MarketOdds("Real Madrid", "Barcelona", "h2h", "sample", "Barcelona", 3.40),
        MarketOdds("Real Madrid", "Barcelona", "totals", "sample", "Over", 1.90, 2.5),
        MarketOdds("Real Madrid", "Barcelona", "totals", "sample", "Under", 1.95, 2.5),
    ]
