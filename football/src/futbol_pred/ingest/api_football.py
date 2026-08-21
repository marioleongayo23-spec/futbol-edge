"""Cliente de API-Football (v3) para fixtures, resultados y estadísticas.

Docs: https://www.api-football.com/documentation-v3
Sin clave, ``get_fixtures`` devuelve un pequeño conjunto de ejemplo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from ..config import LEAGUES, settings

BASE_URL = "https://v3.football.api-sports.io"


@dataclass
class Fixture:
    api_id: int
    league: str
    season: int
    kickoff: datetime
    home_team: str
    away_team: str
    status: str
    home_goals: int | None = None
    away_goals: int | None = None
    matchday: int | None = None
    stage: str | None = None
    source: str = "api_football"
    home_crest: str | None = None
    away_crest: str | None = None
    home_tla: str | None = None
    away_tla: str | None = None


class ApiFootballClient:
    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or settings.api_football_key
        self.timeout = timeout

    @property
    def offline(self) -> bool:
        return not self.api_key

    def _get(self, path: str, params: dict) -> dict:
        headers = {"x-apisports-key": self.api_key}
        resp = requests.get(
            f"{BASE_URL}/{path}",
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_fixtures(
        self, league: str, season: int | None = None, last: int | None = None
    ) -> list[Fixture]:
        season = season or settings.season
        if self.offline:
            return _sample_fixtures(league, season)

        params = {"league": LEAGUES[league], "season": season}
        if last:
            params["last"] = last
        data = self._get("fixtures", params)
        out: list[Fixture] = []
        for item in data.get("response", []):
            fx = item["fixture"]
            teams = item["teams"]
            goals = item["goals"]
            out.append(
                Fixture(
                    api_id=fx["id"],
                    league=league,
                    season=season,
                    kickoff=datetime.fromisoformat(
                        fx["date"].replace("Z", "+00:00")
                    ),
                    home_team=teams["home"]["name"],
                    away_team=teams["away"]["name"],
                    status=fx["status"]["short"],
                    home_goals=goals["home"],
                    away_goals=goals["away"],
                )
            )
        return out


def _sample_fixtures(league: str, season: int) -> list[Fixture]:
    """Datos de ejemplo para desarrollo/tests offline."""
    teams = [
        "Real Madrid", "Barcelona", "Atletico Madrid", "Sevilla",
        "Real Sociedad", "Villarreal", "Athletic Club", "Valencia",
    ]
    fixtures: list[Fixture] = []
    fid = 1000
    base = datetime(season, 8, 20, 21, 0)
    # Una mini-liga de ida (resultados inventados pero plausibles).
    scores = [(2, 1), (0, 0), (3, 1), (1, 1), (2, 0), (1, 2), (0, 1), (2, 2)]
    k = 0
    for i in range(len(teams)):
        for j in range(len(teams)):
            if i == j:
                continue
            h, a = scores[k % len(scores)]
            fixtures.append(
                Fixture(
                    api_id=fid,
                    league=league,
                    season=season,
                    kickoff=base + timedelta(days=fid - 1000),
                    home_team=teams[i],
                    away_team=teams[j],
                    status="FT",
                    home_goals=h,
                    away_goals=a,
                )
            )
            fid += 1
            k += 1
    return fixtures
