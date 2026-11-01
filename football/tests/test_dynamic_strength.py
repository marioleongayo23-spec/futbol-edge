from datetime import datetime, timezone, timedelta
import math

import pytest

from futbol_pred.backtest.dynamic_strength import DynamicStrengthPredictor

UTC = timezone.utc
BASE = datetime(2026, 3, 1, 12, tzinfo=UTC)


def fixture(n, hg=2, ag=0, **kwargs):
    row = {
        "kickoff": (BASE + timedelta(days=n)).isoformat(),
        "home": "A", "away": "B", "home_goals": hg, "away_goals": ag,
        "finished": True,
    }
    row.update(kwargs)
    return row


def test_online_strength_makes_sequential_valid_probabilities():
    rows = [fixture(n) for n in range(35)]
    model = DynamicStrengthPredictor(min_matches=15).fit(list(reversed(rows)))
    p = model.predict("A", "B", as_of=BASE + timedelta(days=36))
    assert p is not None
    assert set(p) == {"1", "X", "2"}
    assert all(0 < v < 1 and math.isfinite(v) for v in p.values())
    assert sum(p.values()) == pytest.approx(1.0)
    assert p["1"] > p["2"]
    assert model.diagnostics("A", "B")["promotion"] == "disabled"


def test_cutoff_prevents_any_future_result_from_affecting_prediction():
    past = [fixture(i, 1, 1) for i in range(34)]
    at = BASE + timedelta(days=34)
    future = [fixture(i, 20, 0) for i in range(34, 40)]
    first = DynamicStrengthPredictor().fit(past, as_of=at)
    second = DynamicStrengthPredictor().fit(future + past, as_of=at)
    assert second.n_results == first.n_results == 34
    assert second.predict("A", "B", as_of=at) == first.predict("A", "B", as_of=at)


def test_date_only_public_domain_history_never_becomes_precise_training():
    rows = [fixture(i, kickoff_precision="date_only") for i in range(35)]
    model = DynamicStrengthPredictor(min_matches=1).fit(rows)
    assert model.n_results == 0
    assert model.predict("A", "B") is None


def test_missing_scores_timezone_or_unsafe_values_are_ignored():
    rows = [fixture(0, 1, 0),
            fixture(1, None, 0),
            fixture(2, True, 0),
            fixture(3, -1, 0),
            fixture(4, 1, 1, kickoff="2026-03-05T12:00:00"),
            fixture(5, 1, 0, kickoff="nonsense")]
    model = DynamicStrengthPredictor(min_matches=1).fit(rows)
    assert model.n_results == 1
    with pytest.raises(ValueError):
        model.fit(rows, as_of=datetime(2026, 4, 1, 12))


def test_decay_reduces_strength_after_long_inactivity():
    model = DynamicStrengthPredictor(min_matches=1, decay_per_day=.01)
    model.fit([fixture(i) for i in range(24)])
    near = model.diagnostics("A", "B", as_of=BASE + timedelta(days=25))
    far = model.diagnostics("A", "B", as_of=BASE + timedelta(days=425))
    assert abs(far["expected_goals"][0] - model.prior_home_goals) < (
        abs(near["expected_goals"][0] - model.prior_home_goals)
    )


@pytest.mark.parametrize("params", [
    {"lr": 0.0}, {"lr": 0.9}, {"decay_per_day": -.01},
    {"min_matches": 0}, {"prior_home_goals": 0},
])
def test_reject_invalid_challenger_parameters(params):
    with pytest.raises(ValueError):
        DynamicStrengthPredictor(**params)
