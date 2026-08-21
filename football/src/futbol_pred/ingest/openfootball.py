"""Cliente OpenFootball (football.json): datos libres, sin API key.

https://github.com/openfootball/football.json — dominio público, ideal como
fuente GRATIS de Segunda División (que football-data.org no da en su plan free)
y respaldo de LaLiga/otras. Formato por temporada y liga:
    https://raw.githubusercontent.com/openfootball/football.json/master/<TEMP>/es.<N>.json
  es.1 = Primera (LaLiga), es.2 = Segunda. <TEMP> = "2025-26".

Nota: las fuentes comunitarias suelen publicar la temporada nueva con algo de
retraso; por eso ``get_matches`` cae a la temporada anterior si la actual aún
no existe (útil para sembrar el modelo con las fuerzas de cada equipo).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .api_football import Fixture

RAW_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master"
MADRID = ZoneInfo("Europe/Madrid")

# league -> (código país, número de división en football.json)
LEAGUE_FILE = {
    "laliga": ("es", 1),
    "segunda": ("es", 2),
}


def season_str(season: int) -> str:
    """2025 -> '2025-26'."""
    return f"{season}-{(season + 1) % 100:02d}"


class OpenFootballClient:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def _url(self, league: str, season: int) -> str:
        code, num = LEAGUE_FILE[league]
        return f"{RAW_BASE}/{season_str(season)}/{code}.{num}.json"

    def get_matches(
        self, league: str, season: int, allow_previous: bool = False
    ) -> list[Fixture]:
        """Partidos de la temporada. Con ``allow_previous`` cae a la temporada
        anterior si la actual aún no existe (útil solo para sembrar el modelo;
        NO para mostrar, para no mezclar temporadas)."""
        if league not in LEAGUE_FILE:
            return []
        candidates = (season, season - 1) if allow_previous else (season,)
        for candidate in candidates:
            try:
                resp = requests.get(self._url(league, candidate), timeout=self.timeout)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                return self.parse(resp.json(), league, candidate)
            except requests.HTTPError:
                continue
        return []

    @staticmethod
    def parse(data: dict, league: str, season: int) -> list[Fixture]:
        out: list[Fixture] = []
        fid = 1
        for m in data.get("matches", []):
            score = m.get("score") or {}
            ft = score.get("ft")
            hg = ag = None
            if isinstance(ft, list) and len(ft) == 2:
                hg, ag = ft[0], ft[1]
            kickoff = _parse_dt(m.get("date"), m.get("time"))
            out.append(Fixture(
                api_id=fid,
                league=league,
                season=season,
                kickoff=kickoff,
                home_team=m.get("team1", ""),
                away_team=m.get("team2", ""),
                status="FINISHED" if hg is not None else "SCHEDULED",
                home_goals=hg,
                away_goals=ag,
                matchday=_round_num(m.get("round")),
                source="openfootball",
            ))
            fid += 1
        return out


def _parse_dt(date: str | None, time: str | None) -> datetime:
    if not date:
        return datetime(1970, 1, 1, tzinfo=MADRID)
    t = time or "12:00"
    try:
        return datetime.fromisoformat(f"{date}T{t}").replace(tzinfo=MADRID)
    except ValueError:
        return datetime.fromisoformat(date).replace(tzinfo=MADRID)


def _round_num(round_str: str | None) -> int | None:
    """'1. Round' / 'Round 1' / 'Jornada 3' -> 1 / 3."""
    if not round_str:
        return None
    import re

    match = re.search(r"\d+", round_str)
    return int(match.group()) if match else None
