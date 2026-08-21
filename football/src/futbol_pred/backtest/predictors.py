"""Predictores 1X2 con interfaz común, para comparar en el backtest.

Interfaz (duck typing):
    fit(matches: list[dict]) -> self
    predict(home, away) -> dict{'1','X','2'} | None   (None si no puede)

Incluye baselines obligatorios (tu #61): un modelo complejo solo se acepta si
bate consistentemente a estos.
"""

from __future__ import annotations

from collections import Counter

from ..elo import EloRatings
from ..model import DixonColesModel
from ..scheduling import is_finished


def _played(matches: list[dict]) -> list[dict]:
    return [m for m in matches if is_finished(m)]


def _outcome(m: dict) -> str:
    h, a = m["home_goals"], m["away_goals"]
    return "1" if h > a else ("X" if h == a else "2")


class BaselineRates:
    """Baseline 0: frecuencias base de 1/X/2 en el histórico (constantes)."""

    def __init__(self) -> None:
        self.probs = {"1": 1 / 3, "X": 1 / 3, "2": 1 / 3}

    def fit(self, matches: list[dict]) -> "BaselineRates":
        played = _played(matches)
        if played:
            c = Counter(_outcome(m) for m in played)
            n = sum(c.values())
            self.probs = {k: c.get(k, 0) / n for k in ("1", "X", "2")}
        return self

    def predict(self, home: str, away: str) -> dict[str, float] | None:
        return dict(self.probs)


class EloPredictor:
    """Baseline fuerte: probabilidades derivadas de Elo (tu #46)."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.elo = EloRatings(**kwargs)

    def fit(self, matches: list[dict]) -> "EloPredictor":
        self.elo = EloRatings(**self.kwargs)
        for m in sorted(_played(matches), key=lambda x: x.get("kickoff", 0)):
            self.elo.update(m["home"], m["away"], m["home_goals"], m["away_goals"],
                            neutral=bool(m.get("neutral", False)))
        return self

    def predict(self, home: str, away: str) -> dict[str, float] | None:
        return self.elo.match_probabilities(home, away)


class DixonColesPredictor:
    """Modelo Poisson-DixonColes ajustado por máxima verosimilitud."""

    def __init__(self, min_matches: int = 30, fallback: object | None = None):
        self.min_matches = min_matches
        self.model: DixonColesModel | None = None
        # Si no puede predecir (equipo nuevo, pocos datos), delega en Elo.
        self.fallback = fallback if fallback is not None else EloPredictor()

    def fit(self, matches: list[dict]) -> "DixonColesPredictor":
        played = _played(matches)
        self.fallback.fit(matches)
        if len(played) < self.min_matches:
            self.model = None
            return self
        model = DixonColesModel()
        model.fit(
            [m["home"] for m in played],
            [m["away"] for m in played],
            [m["home_goals"] for m in played],
            [m["away_goals"] for m in played],
        )
        self.model = model
        return self

    def predict(self, home: str, away: str) -> dict[str, float] | None:
        if self.model and home in self.model.attack and away in self.model.attack:
            return self.model.predict_matrix(home, away).one_x_two()
        return self.fallback.predict(home, away)
