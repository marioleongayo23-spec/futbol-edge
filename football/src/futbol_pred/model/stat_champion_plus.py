"""Challenger causal para mercados estadísticos disciplinarios.

Construye features estrictamente *as-of*: cada fila de entrenamiento se genera
solo con partidos anteriores a su kickoff. La capa está deliberadamente limitada
a las estadísticas que NO alimentan pseudo-xG/1X2. El árbitro se mantiene fuera
de este modelo porque Fútbol Edge ya tiene una capa específica posterior con
shrinkage/ajuste de árbitro; incluirlo aquí duplicaría la misma señal.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
import math

import numpy as np

from ..ingest.football_data_uk import MatchStats
from ..normalize import canonical_team

PLUS_SCHEMA = "stat-regression-plus-v1"
PLUS_FEATURES = (
    "ataque_propio_asof",
    "defensa_rival_asof",
    "media_liga_lado_asof",
    "forma_reciente_5",
    "descanso_dias",
    "local",
    "intercept",
)
MIN_CAUSAL_ROWS = 50
RECENT_WINDOW = 5
RIDGE = 8.0


@dataclass
class _SideAccum:
    own_sum: float = 0.0
    against_sum: float = 0.0
    n: int = 0

    def add(self, own: float, against: float) -> None:
        self.own_sum += float(own)
        self.against_sum += float(against)
        self.n += 1

    @property
    def own_avg(self) -> float | None:
        return self.own_sum / self.n if self.n else None

    @property
    def against_avg(self) -> float | None:
        return self.against_sum / self.n if self.n else None


@dataclass
class CausalStatState:
    home: dict = field(default_factory=lambda: defaultdict(_SideAccum))
    away: dict = field(default_factory=lambda: defaultdict(_SideAccum))
    league_home: _SideAccum = field(default_factory=_SideAccum)
    league_away: _SideAccum = field(default_factory=_SideAccum)
    recent: dict = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=RECENT_WINDOW)))
    last_kickoff: dict[str, datetime] = field(default_factory=dict)
    matches_seen: int = 0

    def update(self, match: MatchStats, stat: str) -> None:
        actual = match.stats.get(stat)
        if actual is None:
            return
        home = canonical_team(match.home_team)
        away = canonical_team(match.away_team)
        hv, av = float(actual[0]), float(actual[1])
        self.home[home].add(hv, av)
        self.away[away].add(av, hv)
        self.league_home.add(hv, av)
        self.league_away.add(av, hv)
        self.recent[home].append(hv)
        self.recent[away].append(av)
        if isinstance(match.kickoff, datetime):
            self.last_kickoff[home] = match.kickoff
            self.last_kickoff[away] = match.kickoff
        self.matches_seen += 1

    def serialise(self) -> dict:
        def side_map(rows: dict) -> dict:
            return {
                team: {"own_sum": row.own_sum, "against_sum": row.against_sum, "n": row.n}
                for team, row in rows.items()
            }
        return {
            "home": side_map(self.home),
            "away": side_map(self.away),
            "league_home": {
                "own_sum": self.league_home.own_sum,
                "against_sum": self.league_home.against_sum,
                "n": self.league_home.n,
            },
            "league_away": {
                "own_sum": self.league_away.own_sum,
                "against_sum": self.league_away.against_sum,
                "n": self.league_away.n,
            },
            "recent": {team: list(values) for team, values in self.recent.items()},
            "last_kickoff": {
                team: value.isoformat() for team, value in self.last_kickoff.items()
            },
            "matches_seen": self.matches_seen,
        }


def _avg(sum_value: float, n: int) -> float | None:
    return float(sum_value) / int(n) if int(n) > 0 else None


def _state_value(state: CausalStatState | dict, bucket: str, team: str, key: str) -> float | None:
    if isinstance(state, CausalStatState):
        row = getattr(state, bucket).get(team)
        return getattr(row, key) if row is not None else None
    row = (state.get(bucket) or {}).get(team) or {}
    if key == "own_avg":
        return _avg(row.get("own_sum", 0.0), row.get("n", 0))
    if key == "against_avg":
        return _avg(row.get("against_sum", 0.0), row.get("n", 0))
    return None


def _league_value(state: CausalStatState | dict, bucket: str, key: str) -> float | None:
    if isinstance(state, CausalStatState):
        row = getattr(state, bucket)
        return getattr(row, key)
    row = state.get(bucket) or {}
    if key == "own_avg":
        return _avg(row.get("own_sum", 0.0), row.get("n", 0))
    if key == "against_avg":
        return _avg(row.get("against_sum", 0.0), row.get("n", 0))
    return None


def _recent_values(state: CausalStatState | dict, team: str) -> list[float]:
    if isinstance(state, CausalStatState):
        return [float(v) for v in state.recent.get(team, ())]
    return [float(v) for v in (state.get("recent") or {}).get(team, ())]


def _last_kickoff(state: CausalStatState | dict, team: str) -> datetime | None:
    if isinstance(state, CausalStatState):
        return state.last_kickoff.get(team)
    raw = (state.get("last_kickoff") or {}).get(team)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _rest_days(kickoff: datetime | None, previous: datetime | None) -> float:
    if kickoff is None or previous is None:
        return 7.0
    try:
        days = (kickoff - previous).total_seconds() / 86400.0
    except TypeError:
        days = (kickoff.replace(tzinfo=None) - previous.replace(tzinfo=None)).total_seconds() / 86400.0
    if not math.isfinite(days) or days <= 0:
        return 7.0
    return float(min(14.0, max(2.0, days)))


def features_from_state(
    state: CausalStatState | dict,
    home: str,
    away: str,
    *,
    home_side: bool,
    kickoff: datetime | None,
) -> list[float] | None:
    home = canonical_team(home)
    away = canonical_team(away)
    if home_side:
        own = _state_value(state, "home", home, "own_avg")
        opp = _state_value(state, "away", away, "against_avg")
        league = _league_value(state, "league_home", "own_avg")
        team = home
        indicator = 1.0
    else:
        own = _state_value(state, "away", away, "own_avg")
        opp = _state_value(state, "home", home, "against_avg")
        league = _league_value(state, "league_away", "own_avg")
        team = away
        indicator = 0.0
    if league is None:
        return None
    own = float(own if own is not None else league)
    opp = float(opp if opp is not None else league)
    recent = _recent_values(state, team)
    recent_mean = float(np.mean(recent)) if recent else own
    rest = _rest_days(kickoff, _last_kickoff(state, team))
    return [own, opp, float(league), recent_mean, rest, indicator, 1.0]


def _causal_training_rows(matches: list[MatchStats], stat: str) -> tuple[list[list[float]], list[float], CausalStatState]:
    state = CausalStatState()
    rows: list[list[float]] = []
    targets: list[float] = []
    dated = sorted(
        (m for m in matches if isinstance(m.kickoff, datetime)),
        key=lambda m: m.kickoff,
    )
    for match in dated:
        actual = match.stats.get(stat)
        if actual is not None:
            hf = features_from_state(
                state, match.home_team, match.away_team,
                home_side=True, kickoff=match.kickoff,
            )
            af = features_from_state(
                state, match.home_team, match.away_team,
                home_side=False, kickoff=match.kickoff,
            )
            if hf is not None and af is not None and state.matches_seen >= 8:
                rows.extend((hf, af))
                targets.extend((float(actual[0]), float(actual[1])))
        state.update(match, stat)
    return rows, targets, state


def fit_plus_artifact(matches: list[MatchStats], stat: str) -> dict | None:
    rows, targets, final_state = _causal_training_rows(matches, stat)
    if len(rows) < MIN_CAUSAL_ROWS * 2:
        return None
    x = np.asarray(rows, dtype=float)
    y = np.asarray(targets, dtype=float)
    ridge = math.sqrt(RIDGE)
    design = np.vstack((x, ridge * np.eye(x.shape[1])))
    target = np.concatenate((y, np.zeros(x.shape[1], dtype=float)))
    coef, *_ = np.linalg.lstsq(design, target, rcond=None)
    return {
        "schema": PLUS_SCHEMA,
        "stat": stat,
        "features": list(PLUS_FEATURES),
        "coefficients": [float(value) for value in coef],
        "n": len(rows) // 2,
        "causal": True,
        "state": final_state.serialise(),
    }


def predict_plus(
    artifact: dict | None,
    home: str,
    away: str,
    *,
    home_side: bool,
    kickoff: datetime | None,
    state: CausalStatState | dict | None = None,
) -> float | None:
    if not artifact or artifact.get("schema") != PLUS_SCHEMA:
        return None
    coefficients = artifact.get("coefficients")
    if not isinstance(coefficients, list) or len(coefficients) != len(PLUS_FEATURES):
        return None
    active_state = state if state is not None else artifact.get("state")
    if not active_state:
        return None
    features = features_from_state(
        active_state, home, away, home_side=home_side, kickoff=kickoff,
    )
    if features is None:
        return None
    value = float(np.dot(np.asarray(coefficients, dtype=float), np.asarray(features, dtype=float)))
    return max(0.0, value)


def rolling_plus_predictions(
    train: list[MatchStats],
    validation: list[MatchStats],
    stat: str,
) -> tuple[dict | None, list[tuple[MatchStats, float, float]]]:
    """Predice la cola temporal actualizando estado solo después de cada partido."""
    artifact = fit_plus_artifact(train, stat)
    if not artifact:
        return None, []
    # Reconstruimos el estado final del train y luego avanzamos una observación
    # cada vez. El target de un partido jamás entra en sus propias features.
    _, _, state = _causal_training_rows(train, stat)
    out: list[tuple[MatchStats, float, float]] = []
    for match in sorted(validation, key=lambda m: m.kickoff):
        actual = match.stats.get(stat)
        if actual is not None:
            home = predict_plus(
                artifact, match.home_team, match.away_team,
                home_side=True, kickoff=match.kickoff, state=state,
            )
            away = predict_plus(
                artifact, match.home_team, match.away_team,
                home_side=False, kickoff=match.kickoff, state=state,
            )
            if home is not None and away is not None:
                out.append((match, home, away))
        state.update(match, stat)
    return artifact, out
