"""Cliente de The Odds API para cuotas de múltiples casas y submercados.

Docs: https://the-odds-api.com/liveapi/guides/v4/
Sin clave, ``get_odds`` devuelve cuotas de ejemplo.
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


@dataclass
class MarketOdds:
    home_team: str
    away_team: str
    market: str            # 1x2 / totals / spreads
    bookmaker: str
    selection: str
    odds: float
    point: float | None = None  # línea (para totals/spreads)


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


def _sample_odds() -> list[MarketOdds]:
    return [
        MarketOdds("Real Madrid", "Barcelona", "h2h", "sample", "Real Madrid", 2.10),
        MarketOdds("Real Madrid", "Barcelona", "h2h", "sample", "Draw", 3.60),
        MarketOdds("Real Madrid", "Barcelona", "h2h", "sample", "Barcelona", 3.40),
        MarketOdds("Real Madrid", "Barcelona", "totals", "sample", "Over", 1.90, 2.5),
        MarketOdds("Real Madrid", "Barcelona", "totals", "sample", "Under", 1.95, 2.5),
    ]
