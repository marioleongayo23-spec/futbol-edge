"""Challenger de árbitro para faltas y amarillas, validado temporalmente.

El perfil arbitral nunca toca 1X2/goles. Solo puede ajustar las líneas de
``fouls`` y ``yellows`` cuando, sobre una cola temporal no vista, reduce
estrictamente el MAE frente al predictor de equipos sin árbitro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import unicodedata

import numpy as np

from ..ingest.football_data_uk import MatchStats
from .stats_markets import StatsPredictor

REFEREE_STATS = ("fouls", "yellows")
MIN_HISTORY = 80
MIN_VALIDATION = 20
MIN_REFEREE_MATCHES = 6
PRIOR_MATCHES = 8.0
FACTOR_LIMITS = {"fouls": (0.85, 1.15), "yellows": (0.75, 1.25)}


def _tokens(value: str | None) -> tuple[str, ...]:
    text = str(value or "").split(",", 1)[0]
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    raw = re.findall(r"[a-z0-9]+", text)
    # Las fuentes históricas usan a menudo iniciales ("J Alberola Rojas") y
    # API-Football el nombre completo. Ignorar iniciales permite resolver ambas.
    return tuple(token for token in raw if len(token) > 1)


def _ref_key(value: str | None) -> str:
    return " ".join(_tokens(value))


def _dated_with_referee(matches: list[MatchStats]) -> list[MatchStats]:
    return sorted(
        (
            match for match in matches
            if isinstance(match.kickoff, datetime) and _tokens(match.referee)
        ),
        key=lambda match: match.kickoff,
    )


def _split_temporal(rows: list[MatchStats], validation_fraction: float = 0.25):
    if len(rows) < MIN_HISTORY:
        return [], []
    split = max(
        MIN_HISTORY - MIN_VALIDATION,
        min(len(rows) - MIN_VALIDATION, round(len(rows) * (1.0 - validation_fraction))),
    )
    return rows[:split], rows[split:]


@dataclass
class RefereeAdjustmentModel:
    league_sum: dict[str, float] = field(default_factory=dict)
    league_n: dict[str, int] = field(default_factory=dict)
    referee_sum: dict[str, dict[str, float]] = field(default_factory=dict)
    referee_n: dict[str, dict[str, int]] = field(default_factory=dict)
    referee_names: dict[str, str] = field(default_factory=dict)
    accepted_stats: set[str] = field(default_factory=set)
    validation: dict | None = None

    def fit(
        self,
        matches: list[MatchStats],
        *,
        accepted_stats: set[str] | None = None,
        auto_validate: bool = True,
    ) -> "RefereeAdjustmentModel":
        if accepted_stats is None and auto_validate:
            self.validation = validate_referee_adjustment(matches)
            self.accepted_stats = set(self.validation.get("accepted_stats") or [])
        else:
            self.accepted_stats = set(accepted_stats or [])

        for match in matches:
            key = _ref_key(match.referee)
            if not key:
                continue
            self.referee_names.setdefault(key, str(match.referee or "").strip())
            sums = self.referee_sum.setdefault(key, {})
            counts = self.referee_n.setdefault(key, {})
            for stat in REFEREE_STATS:
                pair = match.stats.get(stat)
                if pair is None:
                    continue
                total = float(pair[0]) + float(pair[1])
                self.league_sum[stat] = self.league_sum.get(stat, 0.0) + total
                self.league_n[stat] = self.league_n.get(stat, 0) + 1
                sums[stat] = sums.get(stat, 0.0) + total
                counts[stat] = counts.get(stat, 0) + 1
        return self

    def _resolve(self, referee: str | None) -> str | None:
        wanted = set(_tokens(referee))
        if not wanted:
            return None
        exact = _ref_key(referee)
        if exact in self.referee_sum:
            return exact
        best: tuple[float, str] | None = None
        second = 0.0
        for key in self.referee_sum:
            candidate = set(key.split())
            if not candidate:
                continue
            common = len(wanted & candidate)
            score = common / max(1, min(len(wanted), len(candidate)))
            if best is None or score > best[0]:
                second = best[0] if best else 0.0
                best = (score, key)
            elif score > second:
                second = score
        if not best or best[0] < 0.67:
            return None
        # Evita resolver apellidos ambiguos si hay dos candidatos igual de buenos.
        if second == best[0] and best[0] < 1.0:
            return None
        return best[1]

    def league_average(self, stat: str) -> float | None:
        n = self.league_n.get(stat, 0)
        return self.league_sum.get(stat, 0.0) / n if n else None

    def profile(self, referee: str | None, stat: str) -> dict | None:
        key = self._resolve(referee)
        league_avg = self.league_average(stat)
        if not key or not league_avg or league_avg <= 0:
            return None
        n = self.referee_n.get(key, {}).get(stat, 0)
        if n < MIN_REFEREE_MATCHES:
            return None
        ref_avg = self.referee_sum[key][stat] / n
        shrunk = (n * ref_avg + PRIOR_MATCHES * league_avg) / (n + PRIOR_MATCHES)
        low, high = FACTOR_LIMITS[stat]
        factor = min(high, max(low, shrunk / league_avg))
        return {
            "referee": self.referee_names.get(key) or referee,
            "n": n,
            "referee_avg": round(ref_avg, 3),
            "league_avg": round(league_avg, 3),
            "shrunk_avg": round(shrunk, 3),
            "factor": round(factor, 4),
            "accepted": stat in self.accepted_stats,
        }

    def context(self, referee: str | None) -> dict | None:
        metrics = {
            stat: profile
            for stat in REFEREE_STATS
            if (profile := self.profile(referee, stat)) is not None
        }
        if not metrics:
            return None
        accepted = [stat for stat, row in metrics.items() if row["accepted"]]
        return {
            "method": "shrunk-referee-total-holdout",
            "gate": "strictly_lower_mae_per_stat",
            "accepted_stats": accepted,
            "metrics": metrics,
            "validation": self.validation,
        }

    def adjust_stats(self, stats: dict | None, referee: str | None) -> tuple[dict | None, list[str]]:
        if not stats:
            return stats, []
        out = {key: dict(value) if isinstance(value, dict) else value for key, value in stats.items()}
        applied: list[str] = []
        for stat in REFEREE_STATS:
            row = out.get(stat)
            profile = self.profile(referee, stat)
            if not isinstance(row, dict) or not profile or not profile["accepted"]:
                continue
            factor = float(profile["factor"])
            try:
                home = float(row["home"]) * factor
                away = float(row["away"]) * factor
            except (KeyError, TypeError, ValueError):
                continue
            row["home"] = round(home, 2)
            row["away"] = round(away, 2)
            row["total"] = round(home + away, 2)
            applied.append(stat)
        return out, applied


def validate_referee_adjustment(matches: list[MatchStats]) -> dict:
    """Holdout temporal: challenger arbitral vs predictor de equipos puro."""
    dated = _dated_with_referee(matches)
    train, validation = _split_temporal(dated)
    if not train or not validation:
        return {
            "method": "referee-time-holdout",
            "status": "blocked_insufficient_dated_sample",
            "accepted": False,
            "accepted_stats": [],
            "n": len(dated),
            "minimum_required": MIN_HISTORY,
            "validation": {},
        }

    baseline = StatsPredictor().fit(
        train,
        temporal_stats=set(),
        auto_temporal=False,
        fit_pseudo_xg=False,
    )
    challenger = RefereeAdjustmentModel().fit(
        train,
        accepted_stats=set(REFEREE_STATS),
        auto_validate=False,
    )
    report: dict[str, dict] = {}
    accepted_stats: list[str] = []
    for stat in REFEREE_STATS:
        base_errors: list[float] = []
        ref_errors: list[float] = []
        for match in validation:
            actual = match.stats.get(stat)
            profile = challenger.profile(match.referee, stat)
            if actual is None or not profile:
                continue
            predicted = baseline.predict_fixture(match.home_team, match.away_team).get(stat)
            if not predicted:
                continue
            actual_total = float(actual[0]) + float(actual[1])
            baseline_total = float(predicted["total"])
            adjusted_total = baseline_total * float(profile["factor"])
            base_errors.append(abs(baseline_total - actual_total))
            ref_errors.append(abs(adjusted_total - actual_total))
        if not base_errors:
            continue
        n = len(base_errors)
        baseline_mae = float(np.mean(base_errors))
        referee_mae = float(np.mean(ref_errors))
        improved = n >= MIN_VALIDATION and referee_mae < baseline_mae
        report[stat] = {
            "n": n,
            "baseline_mae": round(baseline_mae, 4),
            "referee_mae": round(referee_mae, 4),
            "delta": round(referee_mae - baseline_mae, 4),
            "accepted": improved,
        }
        if improved:
            accepted_stats.append(stat)
    return {
        "method": "referee-time-holdout",
        "status": "accepted_partial" if accepted_stats else "blocked_by_gate",
        "accepted": bool(accepted_stats),
        "accepted_stats": accepted_stats,
        "n_train": len(train),
        "n_validation": len(validation),
        "gate": "strictly_lower_mae_per_stat",
        "validation": report,
    }
