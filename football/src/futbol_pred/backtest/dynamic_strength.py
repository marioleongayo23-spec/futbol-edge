"""Causal dynamic attack/defence challenger; NOT the production champion.

An online, regularised Poisson intensity updater. A new match updates the
ratings only *after* its result is known. No outcome from the forecasted match
or post-kickoff facts can influence its predicted probabilities.

This is a deliberately small CPU-only challenger, not a claim of uplift or
a replacement for the validated Dixon-Coles engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

from ..model.dixon_coles import DixonColesModel

UTC = timezone.utc


def _kickoff(value) -> datetime | None:
    try:
        if isinstance(value, (float, int)):
            stamp = datetime.fromtimestamp(value, tz=UTC)
        elif isinstance(value, datetime):
            stamp = value
        elif isinstance(value, str):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


@dataclass
class DynamicStrengthPredictor:
    """Sequential Poisson attack/conceding log-ratings with temporal decay."""

    lr: float = 0.055
    decay_per_day: float = 0.0010
    prior_home_goals: float = 1.46
    prior_away_goals: float = 1.18
    min_matches: int = 30
    log_attack: dict[str, float] = field(default_factory=dict)
    log_concede: dict[str, float] = field(default_factory=dict)
    matches_seen: dict[str, int] = field(default_factory=dict)
    last_seen: dict[str, datetime] = field(default_factory=dict)
    n_results: int = 0

    def __post_init__(self) -> None:
        if (not 0 < self.lr <= 0.2 or
                not 0 <= self.decay_per_day < 0.1 or
                not 0 < self.prior_home_goals <= 5 or
                not 0 < self.prior_away_goals <= 5 or
                not isinstance(self.min_matches, int) or self.min_matches < 1):
            raise ValueError("invalid dynamic strength parameters")

    def _decayed(self, team: str, as_of: datetime | None) -> tuple[float, float]:
        last = self.last_seen.get(team)
        days = max(0.0, (as_of - last).total_seconds() / 86400.0) if last and as_of else 0.0
        shrink = math.exp(-self.decay_per_day * days)
        return self.log_attack.get(team, 0.0) * shrink, self.log_concede.get(team, 0.0) * shrink

    def _rates(self, home: str, away: str, as_of: datetime | None = None) -> tuple[float, float]:
        ah, ch = self._decayed(home, as_of)
        aa, ca = self._decayed(away, as_of)
        home_rate = self.prior_home_goals * math.exp(max(-1.5, min(1.5, ah + ca)))
        away_rate = self.prior_away_goals * math.exp(max(-1.5, min(1.5, aa + ch)))
        return min(5.0, max(0.15, home_rate)), min(5.0, max(0.15, away_rate))

    def fit(self, matches: list[dict], *, as_of: datetime | None = None) -> "DynamicStrengthPredictor":
        """Reset and fit only known finished games strictly earlier than as_of."""
        self.log_attack.clear()
        self.log_concede.clear()
        self.matches_seen.clear()
        self.last_seen.clear()
        self.n_results = 0
        cutoff = _kickoff(as_of) if as_of is not None else None
        if as_of is not None and cutoff is None:
            raise ValueError("as_of must have an explicit timezone")
        usable = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            stamp = _kickoff(match.get("kickoff"))
            if stamp is None or (cutoff is not None and stamp >= cutoff):
                continue
            if match.get("kickoff_precision") == "date_only":
                continue
            home, away = match.get("home"), match.get("away")
            hg, ag = match.get("home_goals"), match.get("away_goals")
            if (not home or not away or home == away or
                    type(hg) is not int or type(ag) is not int or
                    not (0 <= hg <= 30 and 0 <= ag <= 30)):
                continue
            usable.append((stamp, home, away, hg, ag))
        for stamp, home, away, hg, ag in sorted(usable, key=lambda m: m[0]):
            lh, la = self._rates(home, away, stamp)
            # Relative Poisson score updates and L2 damping avoid fitting
            # spurious 10-goal intensity after one surprising result.
            eh, ea = max(-3.0, min(3.0, (hg - lh) / lh)), max(-3.0, min(3.0, (ag - la) / la))
            for team, offensive, defensive in ((home, eh, ea), (away, ea, eh)):
                a, d = self._decayed(team, stamp)
                n = self.matches_seen.get(team, 0)
                step = self.lr / math.sqrt(1.0 + n / 15.0)
                self.log_attack[team] = max(-1.2, min(1.2, 0.995 * a + step * offensive))
                self.log_concede[team] = max(-1.2, min(1.2, 0.995 * d + step * defensive))
                self.matches_seen[team] = n + 1
                self.last_seen[team] = stamp
            self.n_results += 1
        return self

    def predict(self, home: str, away: str, *, as_of: datetime | None = None) -> dict[str, float] | None:
        if self.n_results < self.min_matches or not home or not away or home == away:
            return None
        date = _kickoff(as_of) if as_of is not None else None
        if as_of is not None and date is None:
            raise ValueError("as_of must have an explicit timezone")
        lh, la = self._rates(home, away, date)
        return DixonColesModel.matrix_from_lambdas(lh, la).one_x_two()

    def diagnostics(self, home: str, away: str, *, as_of: datetime | None = None) -> dict:
        date = _kickoff(as_of) if as_of is not None else None
        lh, la = self._rates(home, away, date)
        return {
            "model": "dynamic-poisson-shadow-v1",
            "promotion": "disabled",
            "expected_goals": [round(lh, 3), round(la, 3)],
            "team_history": {home: self.matches_seen.get(home, 0),
                             away: self.matches_seen.get(away, 0)},
            "sample": self.n_results,
            "as_of": date.isoformat() if date else None,
        }
