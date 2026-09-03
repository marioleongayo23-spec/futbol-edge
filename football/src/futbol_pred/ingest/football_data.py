"""Cliente de football-data.org (v4): fixtures y resultados.

Es la fuente estructural fiable de tus prompts (#10, #77): calendario,
jornadas, resultados y estado de partido para LaLiga (PD), Segunda (SD) y
Champions (CL). Trae 'matchday' y 'stage', imprescindibles para la detección
de próxima jornada/fase (scheduling.py).

Header de auth: X-Auth-Token. Sin clave, degrada a los datos de ejemplo del
cliente de API-Football para no romper el pipeline offline.
"""

from __future__ import annotations

import time
from datetime import datetime

import requests

from ..config import LEAGUE_META, settings
from .api_football import Fixture, _sample_fixtures

BASE_URL = "https://api.football-data.org/v4"
FINISHED_STATES = {"FINISHED", "AWARDED"}

# El plan gratis limita a 10 peticiones/minuto. Espaciamos las llamadas para no
# agotar el cupo (era la causa de que Champions fallara con HTTPError/429).
_MIN_GAP = 6.5
_last_call = [0.0]


def _throttle() -> None:
    wait = _MIN_GAP - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


class FootballDataClient:
    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or settings.football_data_api_key
        self.timeout = timeout

    @property
    def offline(self) -> bool:
        return not self.api_key

    def _get(self, path: str, params: dict, _retries: int = 2) -> dict:
        headers = {"X-Auth-Token": self.api_key}
        _throttle()
        resp = requests.get(
            f"{BASE_URL}/{path}", headers=headers, params=params, timeout=self.timeout
        )
        # 429 = rate limit: esperamos y reintentamos (el plan gratis lo marca).
        if resp.status_code == 429 and _retries > 0:
            time.sleep(61)
            return self._get(path, params, _retries=_retries - 1)
        resp.raise_for_status()
        return resp.json()

    def get_matches(
        self,
        league: str,
        season: int | None = None,
        status: str | None = None,
    ) -> list[Fixture]:
        """Descarga partidos de una competición/temporada.

        ``status`` opcional (p. ej. 'FINISHED' o 'SCHEDULED') filtra en origen.
        """
        season = season or settings.season
        if self.offline:
            return _sample_fixtures(league, season)

        code = LEAGUE_META[league]["fd_code"]
        params: dict = {"season": season}
        if status:
            params["status"] = status
        data = self._get(f"competitions/{code}/matches", params)
        return [self._parse(m, league, season) for m in data.get("matches", [])]

    @staticmethod
    def _referee(m: dict) -> str | None:
        """Árbitro principal del partido si football-data.org lo trae (v4 expone
        ``referees`` con tipo REFEREE). En el plan gratis suele venir vacío pre-
        partido; si aparece, encendemos el efecto del árbitro sin coste extra."""
        refs = m.get("referees") or []
        if not isinstance(refs, list):
            return None
        main = next((r for r in refs if str(r.get("type", "")).upper() == "REFEREE"), None)
        name = (main or (refs[0] if refs else {})).get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None

    @staticmethod
    def _parse(m: dict, league: str, season: int) -> Fixture:
        score = m.get("score", {}).get("fullTime", {})
        home = m.get("homeTeam", {})
        away = m.get("awayTeam", {})
        return Fixture(
            api_id=m["id"],
            league=league,
            season=season,
            kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            home_team=home.get("name", ""),
            away_team=away.get("name", ""),
            status=m.get("status", ""),
            home_goals=score.get("home"),
            away_goals=score.get("away"),
            matchday=m.get("matchday"),
            stage=m.get("stage"),
            source="football_data",
            home_crest=home.get("crest"),
            away_crest=away.get("crest"),
            home_tla=home.get("tla"),
            away_tla=away.get("tla"),
            referee=FootballDataClient._referee(m),
        )

    def get_team_meta(self, league: str, season: int | None = None) -> dict:
        """Escudo y colores de club por equipo (gratis). {nombre: {...}}.

        Devuelve {} en modo offline o si el endpoint falla (no es crítico).
        """
        season = season or settings.season
        if self.offline:
            return {}
        code = LEAGUE_META[league]["fd_code"]
        try:
            data = self._get(f"competitions/{code}/teams", {"season": season})
        except Exception:
            return {}
        meta = {}
        for t in data.get("teams", []):
            squad = []
            for player in t.get("squad") or []:
                name = str(player.get("name") or "").strip()
                if name:
                    squad.append({
                        "name": name,
                        "position": str(player.get("position") or "").strip(),
                    })
            meta[t.get("name", "")] = {
                "crest": t.get("crest"),
                "tla": t.get("tla"),
                "colors": t.get("clubColors"),
                "squad": squad,
            }
        return meta
