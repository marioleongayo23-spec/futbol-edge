"""Predicción de estadísticas de partido (córners, tarjetas, remates, faltas...).

Para cada estadística estimamos, por equipo y en total, el valor esperado y la
probabilidad de superar cualquier línea (tu #38-#43). Modelo baseline honesto:
combina la producción del equipo con la concesión del rival (ataque vs defensa),
separando local/visitante, y modela el conteo como Poisson para las líneas.

No inventa picks: devuelve media, desviación y prob_over para que la decisión
salga de un margen real, no de "la media es 10 así que over 9.5".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from scipy.stats import poisson

from ..ingest.football_data_uk import MatchStats
from ..normalize import canonical_team

STAT_NAMES = ("shots", "sot", "corners", "fouls", "yellows", "reds", "goals")


@dataclass
class _Accum:
    for_sum: float = 0.0
    against_sum: float = 0.0
    n: int = 0

    def add(self, f: float, a: float) -> None:
        self.for_sum += f
        self.against_sum += a
        self.n += 1

    @property
    def for_avg(self) -> float | None:
        return self.for_sum / self.n if self.n else None

    @property
    def against_avg(self) -> float | None:
        return self.against_sum / self.n if self.n else None


@dataclass
class StatsPredictor:
    """Ajusta tasas por equipo (local/visitante) y predice estadísticas."""

    # team -> stat -> _Accum, separando condición de local y visitante.
    home: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(_Accum)))
    away: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(_Accum)))
    league_home: dict = field(default_factory=lambda: defaultdict(_Accum))
    league_away: dict = field(default_factory=lambda: defaultdict(_Accum))

    def fit(self, matches: list[MatchStats]) -> "StatsPredictor":
        for m in matches:
            h = canonical_team(m.home_team)
            a = canonical_team(m.away_team)
            for stat, (hv, av) in m.stats.items():
                self.home[h][stat].add(hv, av)   # local: hace hv, concede av
                self.away[a][stat].add(av, hv)   # visitante: hace av, concede hv
                self.league_home[stat].add(hv, av)
                self.league_away[stat].add(av, hv)
        return self

    def _expected(self, home: str, away: str, stat: str) -> tuple[float, float] | None:
        lh = self.league_home[stat].for_avg
        la = self.league_away[stat].for_avg
        if lh is None or la is None:
            return None
        # Producción del equipo y concesión del rival; si falta, cae a media liga.
        h_for = self.home[home][stat].for_avg if self.home[home][stat].n else lh
        a_against = self.away[away][stat].against_avg if self.away[away][stat].n else lh
        a_for = self.away[away][stat].for_avg if self.away[away][stat].n else la
        h_against = self.home[home][stat].against_avg if self.home[home][stat].n else la
        exp_home = (h_for + a_against) / 2.0
        exp_away = (a_for + h_against) / 2.0
        return exp_home, exp_away

    def predict_fixture(self, home: str, away: str) -> dict[str, dict]:
        """Devuelve por estadística: media local/visitante/total y desviación."""
        home = canonical_team(home)
        away = canonical_team(away)
        out: dict[str, dict] = {}
        for stat in STAT_NAMES:
            exp = self._expected(home, away, stat)
            if exp is None:
                continue
            eh, ea = exp
            out[stat] = {
                "home": round(eh, 2),
                "away": round(ea, 2),
                "total": round(eh + ea, 2),
                "home_std": round(eh ** 0.5, 2),
                "away_std": round(ea ** 0.5, 2),
                "total_std": round((eh + ea) ** 0.5, 2),
            }
        return out

    @staticmethod
    def prob_over(mean: float, line: float) -> float:
        """P(conteo > line) bajo Poisson(mean). Línea .5 => sin push."""
        # P(X > line) = 1 - CDF(floor(line))
        import math

        return float(1.0 - poisson.cdf(math.floor(line), mean))

    def market(self, home: str, away: str, stat: str, side: str, line: float) -> dict:
        """Probabilidad over/under de una línea para una estadística/lado.

        side: 'home' | 'away' | 'total'.
        """
        pred = self.predict_fixture(home, away)
        if stat not in pred:
            raise KeyError(f"Estadística no disponible: {stat}")
        mean = pred[stat][side]
        over = self.prob_over(mean, line)
        return {
            "stat": stat,
            "side": side,
            "line": line,
            "mean": mean,
            "prob_over": round(over, 3),
            "prob_under": round(1.0 - over, 3),
        }
