"""Predicción de estadísticas de partido (córners, tarjetas, remates, faltas...).

Para cada estadística estimamos, por equipo y en total, el valor esperado y la
probabilidad de superar cualquier línea. El baseline combina la producción del
equipo con la concesión del rival, separando local/visitante. Cuando existe
muestra fechada suficiente, challengers temporales se validan cronológicamente
antes de entrar en producción.

El histórico de otra división puede entrar como ``auxiliary_matches``. Ese
histórico SOLO alimenta los acumuladores de cada equipo: nunca las medias de la
liga objetivo, la dispersión, el pseudo-xG ni los gates de selección.
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
from .stat_champion_plus import fit_plus_artifact, predict_plus, rolling_plus_predictions

STAT_NAMES = ("shots", "sot", "corners", "fouls", "yellows", "reds", "offsides", "goals")
MIN_TEMPORAL_MATCHES = 80
MIN_TEMPORAL_VALIDATION = 20
DEFAULT_HALF_LIFE_DAYS = 365.25

# P1 statistical champion: solo disciplina se promociona automáticamente en esta
# fase. Remates/SOT/córners alimentan pseudo-xG y, por tanto, el 1X2; no se cambia
# ese camino sin un gate específico del modelo de resultado.
CHAMPION_STATS = ("fouls", "yellows")
REGRESSION_SCHEMA = "stat-regression-v1"
MIN_REGRESSION_MATCHES = 80
MIN_REGRESSION_VALIDATION = 20
REGRESSION_TEAM_MIN = 12
REGRESSION_ADOPT_MARGIN = 0.10


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
    """Valida recencia en una cola temporal y decide por estadística."""

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
        auto_regression=False,
        fit_pseudo_xg=False,
    )
    challenger = StatsPredictor().fit(
        train,
        temporal_stats=set(STAT_NAMES),
        half_life_days=half_life_days,
        auto_temporal=False,
        auto_regression=False,
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

    # P1: artefactos que sí pueden reproducirse en producción. El mapa se obtiene
    # únicamente de una cola temporal no usada para ajustar los coeficientes.
    regression_validation: dict | None = None
    regression_artifacts: dict[str, dict] = field(default_factory=dict)
    regression_plus_artifacts: dict[str, dict] = field(default_factory=dict)
    regression_methods_by_team: dict[str, dict[str, str]] = field(default_factory=dict)

    def fit(
        self,
        matches: list[MatchStats],
        temporal_stats: set[str] | None = None,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        auto_temporal: bool = True,
        fit_pseudo_xg: bool = True,
        auxiliary_matches: list[MatchStats] | None = None,
        auto_regression: bool = True,
    ) -> "StatsPredictor":
        """Ajusta el predictor con una liga primaria y, opcionalmente, memoria auxiliar.

        ``matches`` es la única muestra que define el entorno de la liga objetivo.
        ``auxiliary_matches`` únicamente añade historia a los equipos que aparecen
        allí; jamás entra en medias de liga, dispersión, pseudo-xG ni validación.
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

        # El gate se calcula solo con la liga primaria y antes de añadir memoria
        # auxiliar. Los coeficientes de producción se reajustan con TODA la muestra
        # primaria una vez que el challenger ha demostrado mejora fuera de muestra.
        if auto_regression:
            self.regression_validation = validate_regression_champions(matches)
            self.regression_methods_by_team = {
                team: dict(methods)
                for team, methods in (self.regression_validation.get("methods_by_team") or {}).items()
            }
            regression_stats = {
                stat
                for methods in self.regression_methods_by_team.values()
                for stat, method in methods.items()
                if method == "regresion"
            }
            plus_stats = {
                stat
                for methods in self.regression_methods_by_team.values()
                for stat, method in methods.items()
                if method == "regresion_plus"
            }
            self.regression_artifacts = self._fit_regression_artifacts(matches, regression_stats)
            self.regression_plus_artifacts = {
                stat: artifact
                for stat in plus_stats
                if (artifact := fit_plus_artifact(matches, stat)) is not None
            }

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

    def _regression_features(self, home: str, away: str, stat: str, *, home_side: bool) -> list[float] | None:
        lh = self.league_home[stat].for_avg
        la = self.league_away[stat].for_avg
        if lh is None or la is None:
            return None
        if home_side:
            own = self.home[home][stat].for_avg if self.home[home][stat].n else lh
            opp = self.away[away][stat].against_avg if self.away[away][stat].n else lh
            league = lh
        else:
            own = self.away[away][stat].for_avg if self.away[away][stat].n else la
            opp = self.home[home][stat].against_avg if self.home[home][stat].n else la
            league = la
        return [float(own), float(opp), float(league), 1.0]

    def _fit_regression_artifact(self, matches: list[MatchStats], stat: str) -> dict | None:
        rows: list[list[float]] = []
        targets: list[float] = []
        for match in matches:
            actual = match.stats.get(stat)
            if not actual:
                continue
            home = canonical_team(match.home_team)
            away = canonical_team(match.away_team)
            hf = self._regression_features(home, away, stat, home_side=True)
            af = self._regression_features(home, away, stat, home_side=False)
            if hf is None or af is None:
                continue
            rows.extend((hf, af))
            targets.extend((float(actual[0]), float(actual[1])))
        if len(rows) < 30:
            return None
        coef, *_ = np.linalg.lstsq(np.asarray(rows, dtype=float), np.asarray(targets, dtype=float), rcond=None)
        return {
            "schema": REGRESSION_SCHEMA,
            "stat": stat,
            "features": ["ataque_propio", "defensa_rival", "media_liga_lado", "intercept"],
            "coefficients": [float(value) for value in coef],
            "n": len(rows) // 2,
        }

    def _fit_regression_artifacts(self, matches: list[MatchStats], stats: set[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for stat in sorted(stats):
            artifact = self._fit_regression_artifact(matches, stat)
            if artifact:
                out[stat] = artifact
        return out

    def _regression_expected(
        self,
        home: str,
        away: str,
        stat: str,
        *,
        home_side: bool,
        artifact: dict | None = None,
    ) -> float | None:
        artifact = artifact or self.regression_artifacts.get(stat)
        if not artifact or artifact.get("schema") != REGRESSION_SCHEMA:
            return None
        features = self._regression_features(home, away, stat, home_side=home_side)
        coefficients = artifact.get("coefficients")
        if features is None or not isinstance(coefficients, list) or len(coefficients) != len(features):
            return None
        value = float(np.dot(np.asarray(coefficients, dtype=float), np.asarray(features, dtype=float)))
        return max(0.0, value)

    def method_for(self, team: str, stat: str) -> str:
        team = canonical_team(team)
        method = (self.regression_methods_by_team.get(team) or {}).get(stat)
        if method == "regresion" and stat in self.regression_artifacts:
            return method
        if method == "regresion_plus" and stat in self.regression_plus_artifacts:
            return method
        return "ataque_defensa"

    def predict_fixture(
        self,
        home: str,
        away: str,
        *,
        kickoff: datetime | None = None,
    ) -> dict[str, dict]:
        home = canonical_team(home)
        away = canonical_team(away)
        out: dict[str, dict] = {}
        for stat in STAT_NAMES:
            exp = self._expected(home, away, stat)
            if exp is None:
                continue
            eh, ea = exp
            home_method = self.method_for(home, stat)
            away_method = self.method_for(away, stat)
            if home_method == "regresion":
                candidate = self._regression_expected(home, away, stat, home_side=True)
                if candidate is not None:
                    eh = candidate
                else:
                    home_method = "ataque_defensa"
            elif home_method == "regresion_plus":
                candidate = predict_plus(
                    self.regression_plus_artifacts.get(stat), home, away,
                    home_side=True, kickoff=kickoff,
                )
                if candidate is not None:
                    eh = candidate
                else:
                    home_method = "ataque_defensa"
            if away_method == "regresion":
                candidate = self._regression_expected(home, away, stat, home_side=False)
                if candidate is not None:
                    ea = candidate
                else:
                    away_method = "ataque_defensa"
            elif away_method == "regresion_plus":
                candidate = predict_plus(
                    self.regression_plus_artifacts.get(stat), home, away,
                    home_side=False, kickoff=kickoff,
                )
                if candidate is not None:
                    ea = candidate
                else:
                    away_method = "ataque_defensa"
            out[stat] = {
                "home": round(eh, 2),
                "away": round(ea, 2),
                "total": round(eh + ea, 2),
                "home_std": round(max(0.0, eh) ** 0.5, 2),
                "away_std": round(max(0.0, ea) ** 0.5, 2),
                "total_std": round(max(0.0, eh + ea) ** 0.5, 2),
                "method_home": home_method,
                "method_away": away_method,
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


def validate_regression_champions(
    matches: list[MatchStats],
    *,
    stats: tuple[str, ...] = CHAMPION_STATS,
    train_fraction: float = 0.8,
) -> dict:
    """Elige champion por equipo+stat con validación temporal y control de sesgo.

    ``regresion_plus`` se entrena con features as-of generadas exclusivamente a
    partir de partidos anteriores. En la cola de validación el estado avanza
    partido a partido, como ocurriría en producción. Solo disciplina participa
    en este gate, por lo que pseudo-xG/1X2 permanecen aislados.
    """
    dated = _dated_rows(matches)
    if len(dated) < MIN_REGRESSION_MATCHES:
        return {
            "schema": REGRESSION_SCHEMA,
            "status": "blocked_insufficient_dated_sample",
            "accepted": False,
            "minimum_required": MIN_REGRESSION_MATCHES,
            "n": len(dated),
            "methods_by_team": {},
            "by_stat": {},
        }

    split = min(
        len(dated) - MIN_REGRESSION_VALIDATION,
        max(1, round(len(dated) * train_fraction)),
    )
    train, validation = dated[:split], dated[split:]
    if len(validation) < MIN_REGRESSION_VALIDATION:
        return {
            "schema": REGRESSION_SCHEMA,
            "status": "blocked_insufficient_validation",
            "accepted": False,
            "n_train": len(train),
            "n_validation": len(validation),
            "methods_by_team": {},
            "by_stat": {},
        }

    predictor = StatsPredictor().fit(
        train,
        auto_regression=False,
        fit_pseudo_xg=False,
    )
    artifacts = predictor._fit_regression_artifacts(train, set(stats))
    plus_artifacts: dict[str, dict] = {}
    plus_predictions: dict[str, dict[tuple[str, str, str], tuple[float, float]]] = {}
    for stat in stats:
        artifact, rows = rolling_plus_predictions(train, validation, stat)
        if artifact:
            plus_artifacts[stat] = artifact
        mapped: dict[tuple[str, str, str], tuple[float, float]] = {}
        for match, home_value, away_value in rows:
            key = (
                match.kickoff.isoformat(),
                canonical_team(match.home_team),
                canonical_team(match.away_team),
            )
            mapped[key] = (float(home_value), float(away_value))
        plus_predictions[stat] = mapped

    team_errors: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    team_signed: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    stat_errors: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for match in validation:
        home = canonical_team(match.home_team)
        away = canonical_team(match.away_team)
        match_key = (match.kickoff.isoformat(), home, away)
        for stat in stats:
            actual = match.stats.get(stat)
            default = predictor._expected(home, away, stat)
            if not actual or default is None:
                continue
            default_h, default_a = default
            candidates: dict[str, tuple[float, float]] = {
                "ataque_defensa": (float(default_h), float(default_a))
            }
            artifact = artifacts.get(stat)
            if artifact:
                rh = predictor._regression_expected(home, away, stat, home_side=True, artifact=artifact)
                ra = predictor._regression_expected(home, away, stat, home_side=False, artifact=artifact)
                if rh is not None and ra is not None:
                    candidates["regresion"] = (float(rh), float(ra))
            plus_pair = (plus_predictions.get(stat) or {}).get(match_key)
            if plus_pair:
                candidates["regresion_plus"] = plus_pair

            sides = ((home, float(actual[0]), 0), (away, float(actual[1]), 1))
            for team, real, idx in sides:
                for method, pair in candidates.items():
                    pred = float(pair[idx])
                    err = pred - real
                    team_errors[team][stat][method].append(abs(err))
                    team_signed[team][stat][method].append(err)
                    stat_errors[stat][method].append(abs(err))

    methods_by_team: dict[str, dict[str, str]] = {}
    team_report: dict[str, dict] = {}
    for team, stat_map in team_errors.items():
        for stat, methods in stat_map.items():
            base = methods.get("ataque_defensa") or []
            if len(base) < REGRESSION_TEAM_MIN:
                continue
            base_mae = float(np.mean(base))
            base_bias = float(np.mean(team_signed[team][stat]["ataque_defensa"]))
            candidates_report: dict[str, dict] = {}
            winner = "ataque_defensa"
            winner_mae = base_mae
            for method in ("regresion", "regresion_plus"):
                values = methods.get(method) or []
                signed = team_signed[team][stat].get(method) or []
                if len(values) != len(base) or not values:
                    continue
                mae = float(np.mean(values))
                bias = float(np.mean(signed))
                gain = (1.0 - mae / base_mae) if base_mae > 0 else 0.0
                bias_ok = abs(bias) <= abs(base_bias) + 0.25
                passed = (
                    base_mae > 0
                    and mae <= base_mae * (1.0 - REGRESSION_ADOPT_MARGIN)
                    and bias_ok
                )
                candidates_report[method] = {
                    "mae": round(mae, 4),
                    "bias": round(bias, 4),
                    "gain_pct": round(gain * 100.0, 1),
                    "bias_gate": bias_ok,
                    "passed": passed,
                }
                if passed and mae < winner_mae:
                    winner = method
                    winner_mae = mae
            if winner != "ataque_defensa":
                methods_by_team.setdefault(team, {})[stat] = winner
            team_report.setdefault(team, {})[stat] = {
                "n": len(base),
                "default_mae": round(base_mae, 4),
                "default_bias": round(base_bias, 4),
                "candidates": candidates_report,
                "accepted": winner != "ataque_defensa",
                "method": winner,
            }

    by_stat: dict[str, dict] = {}
    for stat, methods in stat_errors.items():
        base = methods.get("ataque_defensa") or []
        if not base:
            continue
        row = {
            "n": len(base) // 2,
            "default_mae": round(float(np.mean(base)), 4),
            "artifact": artifacts.get(stat),
            "plus_artifact": plus_artifacts.get(stat),
        }
        for method in ("regresion", "regresion_plus"):
            values = methods.get(method) or []
            if values:
                mae = float(np.mean(values))
                row[f"{method}_mae"] = round(mae, 4)
                row[f"{method}_gain_pct"] = round(
                    (1.0 - mae / float(np.mean(base))) * 100.0, 1
                ) if float(np.mean(base)) > 0 else None
        # Compatibilidad con consumidores/tests v1.
        if "regresion_mae" in row:
            row["regression_mae"] = row["regresion_mae"]
            row["gain_pct"] = row.get("regresion_gain_pct")
        by_stat[stat] = row

    accepted = bool(methods_by_team)
    return {
        "schema": REGRESSION_SCHEMA,
        "status": "accepted_partial" if accepted else "blocked_by_gate",
        "accepted": accepted,
        "gate": {
            "default": "ataque_defensa",
            "challengers": ["regresion", "regresion_plus"],
            "min_team_validation_n": REGRESSION_TEAM_MIN,
            "min_relative_mae_gain": REGRESSION_ADOPT_MARGIN,
            "bias_tolerance": 0.25,
            "chronological": True,
            "regresion_plus_causal_asof": True,
            "scope": list(CHAMPION_STATS),
            "affects_pseudo_xg": False,
            "affects_1x2": False,
        },
        "n_train": len(train),
        "n_validation": len(validation),
        "train_end": train[-1].kickoff.isoformat() if train and train[-1].kickoff else None,
        "validation_start": validation[0].kickoff.isoformat() if validation and validation[0].kickoff else None,
        "methods_by_team": methods_by_team,
        "by_team": team_report,
        "by_stat": by_stat,
    }
