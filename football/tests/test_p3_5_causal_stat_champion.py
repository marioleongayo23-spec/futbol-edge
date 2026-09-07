from __future__ import annotations

from datetime import datetime, timedelta, timezone

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.stat_champion_plus import PLUS_SCHEMA, fit_plus_artifact
from futbol_pred.model.stats_markets import CHAMPION_STATS, StatsPredictor, validate_regression_champions


TEAMS = ("Barcelona", "Espanol", "Real Madrid", "Betis")
PAIRS = tuple((home, away) for home in TEAMS for away in TEAMS if home != away)
BASE = {"Barcelona": 0.0, "Espanol": 0.8, "Real Madrid": 1.6, "Betis": 2.4}


def _trending_rows(n: int = 240, *, validation_shock: float = 0.0) -> list[MatchStats]:
    start = datetime(2025, 1, 1, 18, 0, tzinfo=timezone.utc)
    split = round(n * 0.8)
    rows: list[MatchStats] = []
    for i in range(n):
        home, away = PAIRS[i % len(PAIRS)]
        # Tendencia deliberadamente dinámica: las medias estáticas del train se
        # quedan atrás; la forma reciente causal sí puede seguirla.
        trend = 6.0 + 0.12 * i
        shock = validation_shock if i >= split else 0.0
        hf = trend + BASE[home] + shock
        af = trend + BASE[away] + shock
        rows.append(
            MatchStats(
                home_team=home,
                away_team=away,
                kickoff=start + timedelta(days=i),
                referee="Ref A" if i % 2 == 0 else "Ref B",
                stats={
                    "fouls": (hf, af),
                    "yellows": (2.0, 2.0),
                    "shots": (10.0, 10.0),
                    "sot": (4.0, 4.0),
                    "corners": (5.0, 5.0),
                    "goals": (1.0, 1.0),
                },
            )
        )
    return rows


def test_regression_plus_is_causal_and_can_win_the_temporal_gate():
    report = validate_regression_champions(_trending_rows())

    assert report["gate"]["chronological"] is True
    assert report["gate"]["regresion_plus_causal_asof"] is True
    assert report["gate"]["affects_pseudo_xg"] is False
    assert report["gate"]["affects_1x2"] is False
    assert set(report["gate"]["scope"]) == set(CHAMPION_STATS)
    assert any(
        methods.get("fouls") == "regresion_plus"
        for methods in report["methods_by_team"].values()
    )
    plus = report["by_stat"]["fouls"]["plus_artifact"]
    assert plus["schema"] == PLUS_SCHEMA
    assert plus["causal"] is True
    assert "forma_reciente_5" in plus["features"]
    assert "descanso_dias" in plus["features"]


def test_validation_targets_never_retrain_plus_coefficients():
    normal = validate_regression_champions(_trending_rows(validation_shock=0.0))
    shocked = validate_regression_champions(_trending_rows(validation_shock=100.0))

    assert (
        normal["by_stat"]["fouls"]["plus_artifact"]["coefficients"]
        == shocked["by_stat"]["fouls"]["plus_artifact"]["coefficients"]
    )
    assert normal["train_end"] == shocked["train_end"]


def test_production_executes_plus_with_real_fixture_kickoff():
    rows = _trending_rows()
    predictor = StatsPredictor().fit(rows, fit_pseudo_xg=False)
    plus_team = next(
        team
        for team, methods in predictor.regression_methods_by_team.items()
        if methods.get("fouls") == "regresion_plus"
    )
    opponent = next(team for team in TEAMS if team != plus_team)
    kickoff = rows[-1].kickoff + timedelta(days=5)
    prediction = predictor.predict_fixture(plus_team, opponent, kickoff=kickoff)["fouls"]

    assert prediction["method_home"] == "regresion_plus"
    assert prediction["home"] >= 0
    assert "fouls" in predictor.regression_plus_artifacts


def test_plus_training_rows_do_not_depend_on_future_validation_values():
    rows = _trending_rows()
    train = rows[: round(len(rows) * 0.8)]
    artifact = fit_plus_artifact(train, "fouls")

    assert artifact is not None
    assert artifact["schema"] == PLUS_SCHEMA
    assert artifact["causal"] is True
    # Ninguna estadística que alimenta pseudo-xG es elegible para este champion.
    assert "shots" not in CHAMPION_STATS
    assert "sot" not in CHAMPION_STATS
    assert "corners" not in CHAMPION_STATS
