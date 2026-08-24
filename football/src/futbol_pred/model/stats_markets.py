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

import numpy as np
from scipy.optimize import lsq_linear
from scipy.stats import poisson
from scipy.stats import nbinom

from ..ingest.football_data_uk import MatchStats
from ..normalize import canonical_team

STAT_NAMES = ("shots", "sot", "corners", "fouls", "yellows", "reds", "offsides", "goals")


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
    observations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    xg_rows: list[tuple[float, float, float]] = field(default_factory=list)
    xg_coefficients: tuple[float, float, float] = (0.12, 0.025, 0.16)

    def fit(self, matches: list[MatchStats]) -> "StatsPredictor":
        for m in matches:
            h = canonical_team(m.home_team)
            a = canonical_team(m.away_team)
            for stat, (hv, av) in m.stats.items():
                self.home[h][stat].add(hv, av)   # local: hace hv, concede av
                self.away[a][stat].add(av, hv)   # visitante: hace av, concede hv
                self.league_home[stat].add(hv, av)
                self.league_away[stat].add(av, hv)
                self.observations[stat].extend((float(hv), float(av)))
            shots = m.stats.get("shots")
            sot = m.stats.get("sot")
            goals = m.stats.get("goals")
            if shots and sot and goals:
                self.xg_rows.extend([
                    (float(shots[0]), float(sot[0]), float(goals[0])),
                    (float(shots[1]), float(sot[1]), float(goals[1])),
                ])
        self._fit_pseudo_xg()
        return self

    def _fit_pseudo_xg(self) -> None:
        """Aprende una conversión regularizada remates/SOT → goles esperados."""

        if len(self.xg_rows) < 40:
            return
        x = np.asarray([[1.0, shots, sot] for shots, sot, _ in self.xg_rows], dtype=float)
        y = np.asarray([goals for _, _, goals in self.xg_rows], dtype=float)
        prior = np.asarray(self.xg_coefficients, dtype=float)
        # Ridge hacia una conversión futbolística conservadora. Evita que una
        # temporada corta convierta un puñado de goles en coeficientes extremos.
        ridge = 35.0
        design = np.vstack((x, np.sqrt(ridge) * np.eye(3)))
        target = np.concatenate((y, np.sqrt(ridge) * prior))
        fitted = lsq_linear(
            design,
            target,
            bounds=([0.0, 0.0, 0.02], [0.8, 0.10, 0.40]),
        )
        if fitted.success:
            self.xg_coefficients = tuple(float(value) for value in fitted.x)

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

    def pseudo_xg(self, home: str, away: str) -> dict | None:
        """xG proxy gratuito basado en volumen y calidad básica de tiro."""

        pred = self.predict_fixture(home, away)
        if "shots" not in pred or "sot" not in pred:
            return None
        intercept, shot_coef, sot_coef = self.xg_coefficients
        home_xg = intercept + shot_coef * pred["shots"]["home"] + sot_coef * pred["sot"]["home"]
        away_xg = intercept + shot_coef * pred["shots"]["away"] + sot_coef * pred["sot"]["away"]
        # Máximo 25% de influencia aun con tres temporadas completas.
        weight = min(0.25, len(self.xg_rows) / 1600.0)
        return {
            "home": round(max(0.15, min(4.0, home_xg)), 3),
            "away": round(max(0.15, min(4.0, away_xg)), 3),
            "weight": round(weight, 3),
            "n": len(self.xg_rows),
            "coefficients": [round(value, 4) for value in self.xg_coefficients],
        }

    def dispersion(self, stat: str) -> float:
        values = self.observations.get(stat) or []
        if len(values) < 20:
            return 1.0
        mean = float(np.mean(values))
        variance = float(np.var(values, ddof=1))
        return max(1.0, variance / mean) if mean > 0 else 1.0

    @staticmethod
    def prob_over(mean: float, line: float, dispersion: float = 1.0) -> float:
        """P(conteo > línea), Poisson o Negative Binomial si hay dispersión."""
        # P(X > line) = 1 - CDF(floor(line))
        import math

        if dispersion <= 1.05 or mean <= 0:
            return float(1.0 - poisson.cdf(math.floor(line), mean))
        variance = dispersion * mean
        size = max(1e-6, mean * mean / max(1e-6, variance - mean))
        success = size / (size + mean)
        return float(1.0 - nbinom.cdf(math.floor(line), size, success))

    def market(self, home: str, away: str, stat: str, side: str, line: float) -> dict:
        """Probabilidad over/under de una línea para una estadística/lado.

        side: 'home' | 'away' | 'total'.
        """
        pred = self.predict_fixture(home, away)
        if stat not in pred:
            raise KeyError(f"Estadística no disponible: {stat}")
        mean = pred[stat][side]
        dispersion = self.dispersion(stat)
        over = self.prob_over(mean, line, dispersion)
        return {
            "stat": stat,
            "side": side,
            "line": line,
            "mean": mean,
            "distribution": "negative-binomial" if dispersion > 1.05 else "poisson",
            "dispersion": round(dispersion, 3),
            "prob_over": round(over, 3),
            "prob_under": round(1.0 - over, 3),
        }
