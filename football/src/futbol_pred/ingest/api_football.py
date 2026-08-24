"""Cliente de API-Football (v3) para fixtures, resultados y estadísticas.

Docs: https://www.api-football.com/documentation-v3
Sin clave, ``get_fixtures`` devuelve un pequeño conjunto de ejemplo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re
import unicodedata

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
        self._day_cache: dict[str, list[dict]] = {}

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

    def get_squad(self, team_name: str) -> list[dict]:
        """Plantilla actual gratuita; se usa solo para rellenar equipos sin caché."""

        if self.offline or not str(team_name).strip():
            return []
        try:
            teams = self._get("teams", {"search": team_name}).get("response") or []
            if not teams:
                return []
            wanted = str(team_name).casefold()
            chosen = min(
                teams,
                key=lambda item: 0 if str((item.get("team") or {}).get("name") or "").casefold() == wanted else 1,
            )
            team_id = (chosen.get("team") or {}).get("id")
            if not team_id:
                return []
            response = self._get("players/squads", {"team": team_id}).get("response") or []
            players = (response[0].get("players") or []) if response else []
        except Exception:
            return []
        out = []
        for player in players:
            name = str(player.get("name") or "").strip()
            if name:
                out.append({"name": name, "position": str(player.get("position") or "").strip()})
        return out

    @staticmethod
    def _team_key(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
        return re.sub(r"\b(fc|cf|cd|ud|club|deportivo)\b|[^a-z0-9]", "", text)

    def find_fixture(self, home: str, away: str, kickoff: datetime) -> dict | None:
        """Resuelve el id de API-Football por fecha y nombres, sin asumir ids comunes."""

        if self.offline:
            return None
        day = kickoff.date().isoformat()
        if day not in self._day_cache:
            try:
                self._day_cache[day] = self._get("fixtures", {"date": day}).get("response") or []
            except Exception:
                self._day_cache[day] = []
        wanted_home, wanted_away = self._team_key(home), self._team_key(away)
        best = None
        for item in self._day_cache[day]:
            teams = item.get("teams") or {}
            actual_home = self._team_key((teams.get("home") or {}).get("name"))
            actual_away = self._team_key((teams.get("away") or {}).get("name"))
            score = (
                SequenceMatcher(None, wanted_home, actual_home).ratio()
                + SequenceMatcher(None, wanted_away, actual_away).ratio()
            ) / 2
            if best is None or score > best[0]:
                best = (score, item)
        return best[1] if best and best[0] >= 0.72 else None

    @staticmethod
    def _grid_position(grid: str | None, fallback: str | None = None) -> str:
        """Traduce la cuadrícula oficial a demarcaciones compatibles con el campo."""

        try:
            line, column = (int(value) for value in str(grid).split(":"))
        except (TypeError, ValueError):
            line = column = 0
        if line == 1:
            return "POR"
        if line == 2:
            return "LI" if column == 1 else "LD" if column >= 4 else "DFC"
        if line in {3, 4}:
            if column == 1:
                return "MI" if line == 3 else "EI"
            if column >= 4:
                return "MD" if line == 3 else "ED"
            return "MCD" if line == 3 else "MP"
        if line >= 5:
            return "EI" if column == 1 else "ED" if column >= 3 else "DC"
        raw = str(fallback or "").casefold()
        return "POR" if raw == "g" else "DFC" if raw == "d" else "MC" if raw == "m" else "DC"

    def get_official_lineup(self, fixture_id: int) -> list[dict]:
        """Devuelve onces oficiales cuando ambos equipos publicaron 11 titulares."""

        if self.offline:
            return []
        try:
            response = self._get("fixtures/lineups", {"fixture": fixture_id}).get("response") or []
        except Exception:
            return []
        return self._parse_lineups(response)

    def get_fixture_details(self, fixture_ids: list[int]) -> dict[int, dict]:
        """Recupera fixtures detallados en lotes de 20 sin truncar la entrada.

        API-Football permite ``/fixtures?ids=...`` con hasta 20 ids por petición.
        Un fallo de un lote no descarta los lotes que sí respondieron.
        """

        ids = [int(value) for value in dict.fromkeys(fixture_ids) if value]
        if self.offline or not ids:
            return {}
        out: dict[int, dict] = {}
        for start in range(0, len(ids), 20):
            chunk = ids[start:start + 20]
            try:
                response = self._get(
                    "fixtures", {"ids": "-".join(map(str, chunk))}
                ).get("response") or []
            except Exception:
                continue
            for item in response:
                fixture_id = (item.get("fixture") or {}).get("id")
                if fixture_id:
                    out[int(fixture_id)] = item
        return out

    def lineup_from_fixture(self, item: dict | None) -> list[dict]:
        return self._parse_lineups((item or {}).get("lineups") or [])

    @staticmethod
    def _stat_value(value):
        """Convierte porcentajes/cadenas numéricas del proveedor en números."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.endswith("%"):
                raw = raw[:-1].strip()
            try:
                return float(raw)
            except ValueError:
                return value
        return value

    @staticmethod
    def fixture_context(item: dict | None) -> dict:
        """Normaliza árbitro, sede y estadísticas embebidas del batch.

        Las estadísticas son live/post-partido y permanecen separadas del
        snapshot prepartido para impedir leakage.
        """

        item = item or {}
        fixture = item.get("fixture") or {}
        venue = fixture.get("venue") or {}
        context = {
            "provider": "API-Football",
            "referee": fixture.get("referee"),
            "venue": venue.get("name"),
            "city": venue.get("city"),
        }
        statistics = {}
        aliases = {
            "Total Shots": "shots", "Shots on Goal": "sot",
            "Shots off Goal": "shots_off_target", "Blocked Shots": "shots_blocked",
            "Shots insidebox": "shots_inside_box", "Shots outsidebox": "shots_outside_box",
            "Corner Kicks": "corners", "Fouls": "fouls",
            "Yellow Cards": "yellows", "Red Cards": "reds",
            "Offsides": "offsides", "Ball Possession": "possession",
            "Goalkeeper Saves": "saves", "Total passes": "passes",
            "Passes accurate": "passes_accurate", "Passes %": "pass_accuracy",
        }
        for team in item.get("statistics") or []:
            name = str((team.get("team") or {}).get("name") or "").strip()
            values = {}
            for row in team.get("statistics") or []:
                key = aliases.get(row.get("type"))
                if key and row.get("value") is not None:
                    values[key] = ApiFootballClient._stat_value(row["value"])
            if name and values:
                statistics[name] = values
        if statistics:
            context["live_or_post_stats"] = statistics
        return {
            key: value for key, value in context.items()
            if value is not None and value != "" and value != {}
        }

    @classmethod
    def _parse_lineups(cls, response: list[dict]) -> list[dict]:
        out = []
        for team in response:
            starters = []
            for raw in team.get("startXI") or []:
                player = raw.get("player") or {}
                name = str(player.get("name") or "").strip()
                if name:
                    starters.append({
                        "name": name,
                        "position": cls._grid_position(player.get("grid"), player.get("pos")),
                        "grid": player.get("grid"),
                    })
            if len(starters) == 11:
                out.append({
                    "team": str((team.get("team") or {}).get("name") or ""),
                    "formation": team.get("formation"),
                    "coach": str((team.get("coach") or {}).get("name") or ""),
                    "starters": starters,
                })
        return out if len(out) == 2 else []

    def get_absences(self, fixture_id: int) -> list[dict]:
        """Lesiones/sanciones declaradas por API-Football; vacío si el plan no lo ofrece."""

        if self.offline:
            return []
        try:
            response = self._get("injuries", {"fixture": fixture_id}).get("response") or []
        except Exception:
            return []
        out = []
        for item in response:
            player, team = item.get("player") or {}, item.get("team") or {}
            name = str(player.get("name") or "").strip()
            if name:
                out.append({
                    "jugador": name,
                    "team": str(team.get("name") or ""),
                    "estado": str(player.get("type") or "baja").casefold(),
                    "detalle": str(player.get("reason") or player.get("type") or "Baja comunicada"),
                    "source": "API-Football",
                    "official": True,
                })
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
