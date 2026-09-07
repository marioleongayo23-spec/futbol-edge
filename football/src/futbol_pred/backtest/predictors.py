"""Predictores 1X2 con interfaz común, para comparar en el backtest.

Interfaz (duck typing):
    fit(matches: list[dict]) -> self
    predict(home, away) -> dict{'1','X','2'} | None   (None si no puede)

Incluye baselines obligatorios: un modelo complejo solo se acepta si bate
consistentemente a estos. ``HybridDixonColesPredictor`` replica además la capa
pseudo-xG que producción aplica a Dixon-Coles usando exclusivamente estadísticas
de partidos ya disponibles en el tramo de entrenamiento.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from ..elo import EloRatings
from ..ingest.football_data_uk import MatchStats
from ..model import DixonColesModel
from ..model.stats_markets import StatsPredictor
from ..scheduling import is_finished


def _played(matches: list[dict]) -> list[dict]:
    return [m for m in matches if is_finished(m)]


def _outcome(m: dict) -> str:
    h, a = m["home_goals"], m["away_goals"]
    return "1" if h > a else ("X" if h == a else "2")


def _as_match_stats(matches: list[dict]) -> list[MatchStats]:
    """Convierte solo stats históricas ya presentes en el corte de entrenamiento."""
    rows: list[MatchStats] = []
    for match in _played(matches):
        raw = match.get("stats")
        if not isinstance(raw, dict):
            continue
        stats: dict[str, tuple[float, float]] = {}
        for stat, values in raw.items():
            try:
                if isinstance(values, dict):
                    home, away = values["home"], values["away"]
                else:
                    home, away = values[0], values[1]
                stats[str(stat)] = (float(home), float(away))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        if not stats:
            continue
        kickoff = match.get("kickoff")
        if isinstance(kickoff, (int, float)):
            kickoff = datetime.fromtimestamp(float(kickoff), tz=timezone.utc)
        elif not isinstance(kickoff, datetime):
            kickoff = None
        rows.append(MatchStats(
            home_team=match["home"],
            away_team=match["away"],
            stats=stats,
            referee=match.get("referee"),
            kickoff=kickoff,
        ))
    return rows


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
    """Baseline fuerte: probabilidades derivadas de Elo."""

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


class HybridDixonColesPredictor(DixonColesPredictor):
    """Dixon-Coles + pseudo-xG de tiros/SOT con la misma regla que producción.

    La capa estadística se ajusta únicamente con ``matches`` recibidos por el
    walk-forward. Por tanto, ninguna estadística del partido objetivo puede
    entrar en su propia predicción. Si falta cobertura estadística, el resultado
    es exactamente el Dixon-Coles base.
    """

    def __init__(self, min_matches: int = 30, fallback: object | None = None):
        super().__init__(min_matches=min_matches, fallback=fallback)
        self.stats_model: StatsPredictor | None = None
        self.last_context: dict | None = None

    def fit(self, matches: list[dict]) -> "HybridDixonColesPredictor":
        super().fit(matches)
        rows = _as_match_stats(matches)
        self.stats_model = None
        if rows:
            self.stats_model = StatsPredictor().fit(
                rows,
                auto_regression=False,
                fit_pseudo_xg=True,
            )
        self.last_context = None
        return self

    def predict(self, home: str, away: str) -> dict[str, float] | None:
        if not (self.model and home in self.model.attack and away in self.model.attack):
            self.last_context = None
            return self.fallback.predict(home, away)

        matrix = self.model.predict_matrix(home, away)
        eh, ea = matrix.expected_goals()
        pseudo = None
        if self.stats_model is not None:
            try:
                pseudo = self.stats_model.pseudo_xg(home, away)
            except (KeyError, TypeError, ValueError):
                pseudo = None

        if pseudo and pseudo.get("weight", 0) > 0:
            weight = float(pseudo["weight"])
            proxy_home = min(eh * 1.35, max(eh * 0.65, float(pseudo["home"])))
            proxy_away = min(ea * 1.35, max(ea * 0.65, float(pseudo["away"])))
            eh = (1.0 - weight) * eh + weight * proxy_home
            ea = (1.0 - weight) * ea + weight * proxy_away
            matrix = self.model.predict_matrix(home, away, lambdas=(eh, ea))

        probs = matrix.one_x_two()
        self.last_context = {
            "lambda_home": float(eh),
            "lambda_away": float(ea),
            "pseudo_xg": pseudo,
        }
        return probs
