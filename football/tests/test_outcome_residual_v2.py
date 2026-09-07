from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from futbol_pred.backtest import HybridDixonColesPredictor, walk_forward
from futbol_pred.backtest.residual import fit_walk_forward_residual
from futbol_pred.ingest.api_football import Fixture
from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.pipeline import fixtures_to_matches


def test_stats_join_is_canonical_and_never_mixes_barcelona_espanyol():
    kickoff_barca = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    kickoff_espanyol = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)
    fixtures = [
        Fixture(
            api_id=1, league="laliga", season=2026, kickoff=kickoff_barca,
            home_team="FC Barcelona", away_team="Real Madrid CF", status="FINISHED",
            home_goals=2, away_goals=1, matchday=3,
        ),
        Fixture(
            api_id=2, league="laliga", season=2026, kickoff=kickoff_espanyol,
            home_team="RCD Espanyol de Barcelona", away_team="Real Betis Balompié",
            status="FINISHED", home_goals=1, away_goals=0, matchday=3,
        ),
    ]
    stats_rows = [
        MatchStats(
            home_team="Barcelona", away_team="Real Madrid", kickoff=kickoff_barca,
            stats={"shots": (21.0, 8.0), "sot": (9.0, 3.0), "goals": (2.0, 1.0)},
        ),
        MatchStats(
            home_team="Espanol", away_team="Betis", kickoff=kickoff_espanyol,
            stats={"shots": (7.0, 13.0), "sot": (2.0, 5.0), "goals": (1.0, 0.0)},
        ),
    ]

    matches = fixtures_to_matches(fixtures, teams_per_round=10, stats_rows=stats_rows)

    by_home = {match["home"]: match for match in matches}
    assert by_home["FC Barcelona"]["stats"]["shots"] == [21.0, 8.0]
    assert by_home["RCD Espanyol de Barcelona"]["stats"]["shots"] == [7.0, 13.0]
    assert by_home["FC Barcelona"]["stats"] != by_home["RCD Espanyol de Barcelona"]["stats"]


def _hybrid_league(rounds: int = 14) -> list[dict]:
    teams = ["Barcelona", "Espanol", "Real Madrid", "Betis"]
    fixtures = []
    kickoff = 1_750_000_000.0
    for matchday in range(1, rounds + 1):
        if matchday % 2:
            pairs = ((teams[0], teams[1]), (teams[2], teams[3]))
        else:
            pairs = ((teams[0], teams[2]), (teams[1], teams[3]))
        for index, (home, away) in enumerate(pairs):
            home_goal = 2 if home in {"Barcelona", "Real Madrid"} else 1
            away_goal = 1 if away in {"Barcelona", "Real Madrid"} else 0
            fixtures.append({
                "home": home,
                "away": away,
                "home_goals": home_goal,
                "away_goals": away_goal,
                "matchday": matchday,
                "kickoff": kickoff + matchday * 86_400 + index * 3_600,
                "available_at": kickoff + matchday * 86_400 + index * 3_600 + 10_800,
                "status": "FINISHED",
                "competition": "laliga",
                "season": 2026,
                "stats": {
                    "shots": [16.0 if home == "Barcelona" else 10.0, 8.0],
                    "sot": [7.0 if home == "Barcelona" else 4.0, 3.0],
                    "goals": [float(home_goal), float(away_goal)],
                },
            })
    return fixtures


def test_target_match_stats_cannot_leak_into_hybrid_prediction():
    normal = _hybrid_league()
    shocked = deepcopy(normal)
    last_day = max(match["matchday"] for match in shocked)
    for match in shocked:
        if match["matchday"] == last_day:
            match["stats"]["shots"] = [1000.0, 1000.0]
            match["stats"]["sot"] = [900.0, 900.0]
            match["stats"]["goals"] = [50.0, 50.0]

    result_normal = walk_forward(
        normal, HybridDixonColesPredictor(min_matches=4), min_train_rounds=3,
    )
    result_shocked = walk_forward(
        shocked, HybridDixonColesPredictor(min_matches=4), min_train_rounds=3,
    )

    normal_last = [r for r in result_normal.records if r["round"][-1] == last_day]
    shocked_last = [r for r in result_shocked.records if r["round"][-1] == last_day]
    assert normal_last and len(normal_last) == len(shocked_last)
    for left, right in zip(normal_last, shocked_last):
        assert left["home"] == right["home"]
        assert left["away"] == right["away"]
        assert left["probs"] == pytest.approx(right["probs"], abs=1e-12)


def _residual_records(n: int = 100):
    base, elo, dc = [], [], []
    for i in range(n):
        actual = ("1", "X", "2")[i % 3]
        key = {
            "round": ("laliga", "REGULAR", 2026, i + 1),
            "kickoff": float((i + 1) * 86_400),
            "home": f"H{i}",
            "away": f"A{i}",
            "actual": actual,
        }
        base.append({**key, "probs": {"1": 0.44, "X": 0.28, "2": 0.28}})
        elo.append({**key, "probs": {"1": 0.40, "X": 0.30, "2": 0.30}})
        dc.append({**key, "probs": {"1": 0.42, "X": 0.29, "2": 0.29}})
    return base, elo, dc


def test_residual_blocks_when_required_dc_baseline_has_incomplete_coverage():
    base, elo, dc = _residual_records()
    report = fit_walk_forward_residual(
        base,
        elo,
        base_name="hybrid_dixon_coles",
        extra_baseline_records={"dixon_coles": dc[:65]},
    )

    assert report["accepted"] is False
    assert report["status"] == "blocked_incomplete_baseline_coverage"
    coverage = report["baseline_coverage"]["dixon_coles"]
    assert coverage["complete"] is False
    assert coverage["n"] < coverage["required"]
    assert report["acceptance_gate"]["require_complete_extra_baselines"] is True


def test_residual_v2_artifact_is_versioned_and_reproducible():
    base, elo, dc = _residual_records()
    report = fit_walk_forward_residual(
        base,
        elo,
        base_name="hybrid_dixon_coles",
        extra_baseline_records={"dixon_coles": dc},
    )

    artifact = report["production"]
    assert artifact["schema"] == "outcome-residual-v2"
    assert len(artifact["features"]) == 5
    assert len(artifact["weights"]) == 3
    assert report["baseline_coverage"]["dixon_coles"]["complete"] is True
