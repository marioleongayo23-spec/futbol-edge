"""Cliente football-data.co.uk: estadísticas por partido en CSV (sin API key).

Tu fuente #11: CSV gratuitos con estadísticas que football-data.org no da
(remates, tiros a puerta, córners, faltas, tarjetas). Para España:
  LaLiga  -> SP1.csv     Segunda -> SP2.csv
Patrón de temporada: 2025/26 -> "2526".

OJO: no confundir con football-data.ORG. Son fuentes distintas.
Sin red (o en modo offline), devuelve un pequeño conjunto de ejemplo.
"""

from __future__ import annotations

import csv
import io
import zlib
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .api_football import Fixture

BASE_URL = "https://www.football-data.co.uk/mmz4281"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
MADRID = ZoneInfo("Europe/Madrid")

DIV_CODE = {"laliga": "SP1", "segunda": "SP2"}

# Columnas del CSV -> significado (tu tabla del prompt #11).
STAT_COLS = {
    "shots": ("HS", "AS"),
    "sot": ("HST", "AST"),
    "corners": ("HC", "AC"),
    "fouls": ("HF", "AF"),
    "yellows": ("HY", "AY"),
    "reds": ("HR", "AR"),
    "goals": ("FTHG", "FTAG"),
}


@dataclass
class MatchStats:
    home_team: str
    away_team: str
    stats: dict[str, tuple[float, float]]  # nombre -> (local, visitante)


def season_code(season: int) -> str:
    """2025 -> '2526' (temporada 2025/26)."""
    yy = season % 100
    return f"{yy:02d}{(yy + 1) % 100:02d}"


class FootballDataUKClient:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def get_stats(
        self, league: str, season: int, offline: bool = False
    ) -> list[MatchStats]:
        if offline or league not in DIV_CODE:
            return _sample_stats()
        div = DIV_CODE[league]
        url = f"{BASE_URL}/{season_code(season)}/{div}.csv"
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return self.parse(resp.text)

    def get_fixtures(self, league: str, season: int) -> list[Fixture]:
        """Fixtures de Segunda/LaLiga desde co.uk (gratis): jugados con resultado
        (SPx.csv) + próximos (fixtures.csv). Es la vía libre para Segunda, que
        football-data.org no sirve en su plan gratuito."""
        if league not in DIV_CODE:
            return []
        div = DIV_CODE[league]
        out: list[Fixture] = []
        try:
            r = requests.get(f"{BASE_URL}/{season_code(season)}/{div}.csv", timeout=self.timeout)
            r.raise_for_status()
            out += _parse_results(r.text, league, season)
        except requests.RequestException:
            pass
        try:
            r = requests.get(FIXTURES_URL, timeout=self.timeout)
            r.raise_for_status()
            out += _parse_fixtures(r.text, league, season, div)
        except requests.RequestException:
            pass
        return out

    @staticmethod
    def parse(text: str) -> list[MatchStats]:
        reader = csv.DictReader(io.StringIO(text))
        out: list[MatchStats] = []
        for row in reader:
            if not row.get("HomeTeam") or not row.get("AwayTeam"):
                continue
            stats: dict[str, tuple[float, float]] = {}
            for name, (hc, ac) in STAT_COLS.items():
                h, a = _num(row.get(hc)), _num(row.get(ac))
                if h is not None and a is not None:
                    stats[name] = (h, a)
            out.append(MatchStats(row["HomeTeam"], row["AwayTeam"], stats))
        return out


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _stable_id(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode("utf-8")) & 0x7FFFFFFF


def _parse_date(date: str | None, time: str | None) -> datetime | None:
    if not date:
        return None
    date = date.strip()
    t = (time or "").strip() or "16:00"
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(date, fmt)
            try:
                hh, mm = t.split(":")[:2]
                d = d.replace(hour=int(hh), minute=int(mm))
            except (ValueError, IndexError):
                pass
            return d.replace(tzinfo=MADRID)
        except ValueError:
            continue
    return None


def _parse_results(text: str, league: str, season: int) -> list[Fixture]:
    """Partidos jugados de SPx.csv (con fecha y resultado)."""
    out: list[Fixture] = []
    for row in csv.DictReader(io.StringIO(text)):
        home, away = row.get("HomeTeam"), row.get("AwayTeam")
        hg, ag = _int(row.get("FTHG")), _int(row.get("FTAG"))
        if not home or not away or hg is None or ag is None:
            continue
        ko = _parse_date(row.get("Date"), row.get("Time"))
        if ko is None:
            continue
        out.append(Fixture(
            api_id=_stable_id("couk", league, row.get("Date", ""), home, away),
            league=league, season=season, kickoff=ko,
            home_team=home, away_team=away, status="FINISHED",
            home_goals=hg, away_goals=ag, source="football_data_uk",
        ))
    return out


def _parse_fixtures(text: str, league: str, season: int, div: str) -> list[Fixture]:
    """Próximos partidos de fixtures.csv (todas las ligas), filtrados por división."""
    out: list[Fixture] = []
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("Div") or "").strip() != div:
            continue
        home, away = row.get("HomeTeam"), row.get("AwayTeam")
        if not home or not away:
            continue
        ko = _parse_date(row.get("Date"), row.get("Time"))
        if ko is None:
            continue
        out.append(Fixture(
            api_id=_stable_id("couk", league, row.get("Date", ""), home, away),
            league=league, season=season, kickoff=ko,
            home_team=home, away_team=away, status="SCHEDULED",
            home_goals=None, away_goals=None, source="football_data_uk",
        ))
    return out


def _sample_stats() -> list[MatchStats]:
    """Datos de ejemplo (nombres estilo co.uk) para desarrollo offline."""
    base = {
        "shots": (14, 9), "sot": (5, 3), "corners": (6, 4),
        "fouls": (12, 14), "yellows": (2, 3), "reds": (0, 0), "goals": (2, 1),
    }
    teams = ["Barcelona", "Real Madrid", "Ath Madrid", "Sevilla",
             "Sociedad", "Villarreal", "Ath Bilbao", "Valencia"]
    out = []
    for i in range(len(teams)):
        for j in range(len(teams)):
            if i == j:
                continue
            out.append(MatchStats(teams[i], teams[j], dict(base)))
    return out
