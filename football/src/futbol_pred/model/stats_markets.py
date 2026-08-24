"""Predicción de estadísticas de partido (córners, tarjetas, remates, faltas...).

Para cada estadística estimamos, por equipo y en total, el valor esperado y la
probabilidad de superar cualquier línea. El baseline combina la producción del
equipo con la concesión del rival, separando local/visitante. Cuando existe
muestra fechada suficiente, un challenger con decaimiento temporal se valida en
una cola cronológica y solo se activa, estadística a estadística, si reduce el
MAE fuera de muestra. Los conteos usan Poisson o Negative Binomial según la
sobredispersión observada.

El histórico de otra división puede entrar como ``auxiliary_matches``. Ese
histórico SOLO alimenta los acumuladores de cada equipo: nunca las medias de la
liga objetivo, la dispersión, el pseudo-xG ni el gate de recencia. Así un recién
ascendido conserva su identidad estadística sin contaminar el baseline de la
categoría a la que llega.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy.optimize import lsq_linear
from scipy.stats import nbinom, poisson

from ..ingest.football_data_uk import MatchStats
from ..normalize import canonical_team

STAT_NAMES = ("shots", "sot", "corners", "fouls", "yellows", "reds", "offsides", "goals")
MIN_TEMPORAL_MATCHES = 80
MIN_TEMPORAL_VALIDATION = 20
DEFAULT_HALF_LIFE_DAYS = 365.25


@dataclass
class _Accum:
    for_sum: float = 0.0
    against_sum: float = 0.0
    weight_sum: float = 0.0
    n: int = 0

    def add(self, f: float, a: float, weight: float = 1.0) -> None:
        w = max(0.0, float(weight))
        self.for_sum += f * w
        self.against_sum += a * w
        self.weight_sum += w
        self.n += 1

    @property
    def for_avg(self) -> float | None:
        return self.for_sum / self.weight_sum if self.weight_sum > 0 else None

    @property
    def against_avg(self) -> float | None:
        return self.against_sum / self.weight_sum if self.weight_sum > 0 else None


def _dated_rows(matches: list[MatchStats]) -> list[MatchStats]:
    return sorted(
        (match for match in matches if isinstance(match.kickoff, datetime)),
        key=lambda match: match.kickoff,
    )


def _time_weight(kickoff: datetime | None, reference: datetime | None, half_life_days: float) -> float:
    if kickoff is None or reference is None or half_life_days <= 0:
        return 1.0
    try:
        age_days = max(0.0, (reference - kickoff).total_seconds() / 86400.0)
    except TypeError:
        age_days = max(
            0.0,
            (reference.replace(tzinfo=None) - kickoff.replace(tzinfo=None)).total_seconds() / 86400.0,
        )
    return 0.5 ** (age_days / half_life_days)


def _mae_for_stat(predictor: "StatsPredictor", rows: list[MatchStats], stat: str) -> tuple[float | None, int]:
    errors: list[float] = []
    for match in rows:
        actual = match.stats.get(stat)
        if actual is None:
            continue
        predicted = predictor.predict_fixture(match.home_team, match.away_team).get(stat)
        if not predicted:
            continue
        errors.extend((abs(predicted["home"] - actual[0]), abs(predicted["away"] - actual[1])))
    if not errors:
        return None, 0
    return float(np.mean(errors)), len(errors) // 2


def validate_temporal_decay(
    matches: list[MatchStats],
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    validation_fraction: float = 0.25,
) -> dict:
    """Valida recencia en una cola temporal y decide por estadística.

    La cola nunca participa en el ajuste del baseline ni del challenger. Tras la
    selección, el predictor de producción puede reajustarse con todo el histórico,
    pero solo aplica recencia a las estadísticas cuyo MAE validado fue menor.
    """

    dated = _dated_rows(matches)
    if len(dated) < MIN_TEMPORAL_MATCHES:
        return {
            "method": "time-decay-holdout",
            "status": "blocked_insufficient_dated_sample",
            "accepted": False,
            "accepted_stats": [],
            "n": len(dated),
            "minimum_required": MIN_TEMPORAL_MATCHES,
            "half_life_days": half_life_days,
            "validation": {},
        }

    split = max(
        MIN_TEMPORAL_MATCHES - MIN_TEMPORAL_VALIDATION,
        min(len(dated) - MIN_TEMPORAL_VALIDATION, round(len(dated) * (1.0 - validation_fraction))),
    )
    train, validation = dated[:split], dated[split:]
    baseline = StatsPredictor().fit(
        train,
        temporal_stats=set(),
        half_life_days=half_life_days,
        auto_temporal=False,
        fit_pseudo_xg=False,
    )
    challenger = StatsPredictor().fit(
        train,
        temporal_stats=set(STAT_NAMES),
        half_life_days=half_life_days,
        auto_temporal=False,
        fit_pseudo_xg=False,
    )

    report: dict[str, dict] = {}
    accepted_stats: list[str] = []
    for stat in STAT_NAMES:
        baseline_mae, n = _mae_for_stat(baseline, validation, stat)
        challenger_mae, challenger_n = _mae_for_stat(challenger, validation, stat)
        if baseline_mae is None or challenger_mae is None or n != challenger_n:
            continue
        improved = n >= MIN_TEMPORAL_VALIDATION and challenger_mae < baseline_mae
        report[stat] = {
            "n": n,
            "baseline_mae": round(baseline_mae, 4),
            "temporal_mae": round(challenger_mae, 4),
            "delta": round(challenger_mae - baseline_mae, 4),
            "accepted": improved,
        }
        if improved:
            accepted_stats.append(stat)

    return {
        "method": "time-decay-holdout",
        "status": "accepted_partial" if accepted_stats else "blocked_by_gate",
        "accepted": bool(accepted_stats),
        "accepted_stats": accepted_stats,
        "n_train": len(train),
        "n_validation": len(validation),
        "half_life_days": half_life_days,
        "gate": "strictly_lower_mae_per_stat",
        "validation": report,
    }


@dataclass
class StatsPredictor:
    """Ajusta tasas por equipo (local/visitante) y predice estadísticas."""

    home: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(_Accum)))
    away: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(_Accum)))
    league_home: dict = field(default_factory=lambda: defaultdict(_Accum))
    league_away: dict = field(default_factory=lambda: defaultdict(_Accum))
    observations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    xg_rows: list[tuple[float, float, float]] = field(default_factory=list)
    xg_coefficients: tuple[float, float, float] = (0.12, 0.025, 0.16)
    temporal_stats: set[str] = field(default_factory=set)
    temporal_validation: dict | None = None
    auxiliary_rows: int = 0
    auxiliary_teams: set[str] = field(default_factory=set)

    def fit(
        self,
        matches: list[MatchStats],
        temporal_stats: set[str] | None = None,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        auto_temporal: bool = True,
        fit_pseudo_xg: bool = True,
        auxiliary_matches: list[MatchStats] | None = None,
    ) -> "StatsPredictor":
        """Ajusta el predictor con una liga primaria y, opcionalmente, memoria auxiliar.

        ``matches`` es la única muestra que define el entorno de la liga objetivo.
        ``auxiliary_matches`` únicamente añade historia a los equipos que aparecen
        allí; jamás entra en medias de liga, dispersión, pseudo-xG ni validación
        temporal.
        """
        if temporal_stats is None and auto_temporal:
            self.temporal_validation = validate_temporal_decay(matches, half_life_days)
            chosen = set(self.temporal_validation.get("accepted_stats") or [])
        else:
            chosen = set(temporal_stats or [])
        self.temporal_stats = chosen

        dated = _dated_rows(matches)
        reference = dated[-1].kickoff if dated else None
        for m in matches:
            h = canonical_team(m.home_team)
            a = canonical_team(m.away_team)
            recency_weight = _time_weight(m.kickoff, reference, half_life_days)
            for stat, (hv, av) in m.stats.items():
                weight = recency_weight if stat in chosen else 1.0
                self.home[h][stat].add(hv, av, weight)
                self.away[a][stat].add(av, hv, weight)
                self.league_home[stat].add(hv, av, weight)
                self.league_away[stat].add(av, hv, weight)
                self.observations[stat].extend((float(hv), float(av)))
            shots = m.stats.get("shots")
            sot = m.stats.get("sot")
            goals = m.stats.get("goals")
            if shots and sot and goals:
                self.xg_rows.extend([
                    (float(shots[0]), float(sot[0]), float(goals[0])),
                    (float(shots[1]), float(sot[1]), float(goals[1])),
                ])

        if auxiliary_matches:
            self.add_auxiliary_team_history(
                auxiliary_matches,
                reference=reference,
                half_life_days=half_life_days,
            )
        if fit_pseudo_xg:
            self._fit_pseudo_xg()
        return self

    def add_auxiliary_team_history(
        self,
        matches: list[MatchStats],
        *,
        reference: datetime | None = None,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> "StatsPredictor":
        """Añade memoria de equipo sin modificar el entorno estadístico de la liga."""
        if reference is None:
            dated = _dated_rows(matches)
            reference = dated[-1].kickoff if dated else None
        count = 0
        for m in matches:
            h = canonical_team(m.home_team)
            a = canonical_team(m.away_team)
            recency_weight = _time_weight(m.kickoff, reference, half_life_days)
            used = False
            for stat, (hv, av) in m.stats.items():
                weight = recency_weight if stat in self.temporal_stats else 1.0
                self.home[h][stat].add(hv, av, weight)
                self.away[a][stat].add(av, hv, weight)
                used = True
            if used:
                count += 1
                self.auxiliary_teams.update((h, a))
        self.auxiliary_rows += count
        return self

    def _fit_pseudo_xg(self) -> None:
        if len(self.xg_rows) < 40:
            return
        x = np.asarray([[1.0, shots, sot] for shots, sot, _ in self.xg_rows], dtype=float)
        y = np.asarray([goals for _, _, goals in self.xg_rows], dtype=float)
        prior = np.asarray(self.xg_coefficients, dtype=float)
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
        h_for = self.home[home][stat].for_avg if self.home[home][stat].n else lh
        a_against = self.away[away][stat].against_avg if self.away[away][stat].n else lh
        a_for = self.away[away][stat].for_avg if self.away[away][stat].n else la
        h_against = self.home[home][stat].against_avg if self.home[home][stat].n else la
        exp_home = (h_for + a_against) / 2.0
        exp_away = (a_for + h_against) / 2.0
        return exp_home, exp_away

    def predict_fixture(self, home: str, away: str) -> dict[str, dict]:
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
        pred = self.predict_fixture(home, away)
        if "shots" not in pred or "sot" not in pred:
            return None
        intercept, shot_coef, sot_coef = self.xg_coefficients
        home_xg = intercept + shot_coef * pred["shots"]["home"] + sot_coef * pred["sot"]["home"]
        away_xg = intercept + shot_coef * pred["shots"]["away"] + sot_coef * pred["sot"]["away"]
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
        import math
        if dispersion <= 1.05 or mean <= 0:
            return float(1.0 - poisson.cdf(math.floor(line), mean))
        variance = dispersion * mean
        size = max(1e-6, mean * mean / max(1e-6, variance - mean))
        success = size / (size + mean)
        return float(1.0 - nbinom.cdf(math.floor(line), size, success))

    def market(self, home: str, away: str, stat: str, side: str, line: float) -> dict:
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
