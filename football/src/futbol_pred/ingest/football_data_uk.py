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
from dataclasses import dataclass

import requests

BASE_URL = "https://www.football-data.co.uk/mmz4281"

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
