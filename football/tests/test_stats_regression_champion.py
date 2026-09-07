from __future__ import annotations

from datetime import datetime, timedelta, timezone

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.stats_markets import (
    REGRESSION_SCHEMA,
    StatsPredictor,
    validate_regression_champions,
)


TEAMS = ("Barcelona", "Espanol", "Real Madrid", "Betis")
FOULS = {"Barcelona": 5.0, "Espanol": 10.0, "Real Madrid": 15.0, "Betis": 20.0}
PAIRS = tuple((home, away) for home in TEAMS for away in TEAMS if home != away)


def _rows(n: int = 168, *, future_shift: float = 0.0) -> list[MatchStats]:
    start = datetime(2025, 1, 1, 18, 0, tzinfo=timezone.utc)
    split = round(n * 0.8)
    rows = []
    for i in range(n):
        home, away = PAIRS[i % len(PAIRS)]
        shift = future_shift if i >= split else 0.0
        rows.append(
            MatchStats(
                home_team=home,
                away_team=away,
                kickoff=start + timedelta(days=i),
                stats={
                    # La verdad depende casi solo del equipo. Ataque×defensa
                    # diluye esa señal; la regresión puede aprender peso~1 al
                    # ataque propio y ~0 a la concesión rival.
                    "fouls": (FOULS[home] + shift, FOULS[away] + shift),
                    "yellows": (2.0, 2.0),
                    "shots": (10.0, 10.0),
                    "sot": (4.0, 4.0),
                    "corners": (5.0, 5.0),
                    "goals": (1.0, 1.0),
                },
            )
        )
    return rows


def test_regression_gate_promotes_only_after_chronological_improvement():
    report = validate_regression_champions(_rows())

    assert report["accepted"] is True
    assert report["gate"]["chronological"] is True
    assert report["gate"]["min_relative_mae_gain"] == 0.10
    assert any(
        methods.get("fouls") == "regresion"
        for methods in report["methods_by_team"].values()
    )
    assert report["by_stat"]["fouls"]["artifact"]["schema"] == REGRESSION_SCHEMA


def test_validation_future_targets_cannot_change_trained_coefficients():
    normal = validate_regression_champions(_rows(future_shift=0.0))
    shocked = validate_regression_champions(_rows(future_shift=100.0))

    assert (
        normal["by_stat"]["fouls"]["artifact"]["coefficients"]
        == shocked["by_stat"]["fouls"]["artifact"]["coefficients"]
    )
    # El tramo futuro sí puede cambiar si el challenger pasa o no el gate; lo
    # que nunca puede hacer es volver atrás y alterar el modelo entrenado.
    assert normal["n_train"] == shocked["n_train"]
    assert normal["train_end"] == shocked["train_end"]


def test_production_prediction_executes_the_stored_artifact():
    predictor = StatsPredictor().fit(
        _rows(),
        auto_temporal=False,
        temporal_stats=set(),
        auto_regression=False,
        fit_pseudo_xg=False,
    )
    artifact = predictor._fit_regression_artifact(_rows(), "fouls")
    assert artifact is not None

    predictor.regression_artifacts = {"fouls": artifact}
    predictor.regression_methods_by_team = {"Barcelona": {"fouls": "regresion"}}

    features = predictor._regression_features("Barcelona", "Espanol", "fouls", home_side=True)
    expected = predictor._regression_expected("Barcelona", "Espanol", "fouls", home_side=True)
    prediction = predictor.predict_fixture("Barcelona", "Espanol")["fouls"]

    assert features is not None
    assert expected is not None
    assert prediction["method_home"] == "regresion"
    assert prediction["home"] == round(expected, 2)
    assert prediction["method_away"] == "ataque_defensa"


def test_invalid_or_missing_artifact_falls_back_to_default():
    predictor = StatsPredictor().fit(
        _rows(40),
        auto_temporal=False,
        temporal_stats=set(),
        auto_regression=False,
        fit_pseudo_xg=False,
    )
    predictor.regression_methods_by_team = {"Barcelona": {"fouls": "regresion"}}
    predictor.regression_artifacts = {
        "fouls": {"schema": "future-incompatible-schema", "coefficients": [1, 0, 0, 0]}
    }

    prediction = predictor.predict_fixture("Barcelona", "Espanol")["fouls"]

    assert predictor.method_for("Barcelona", "fouls") == "ataque_defensa"
    assert prediction["method_home"] == "ataque_defensa"


def test_small_sample_never_promotes_regression():
    predictor = StatsPredictor().fit(_rows(40), fit_pseudo_xg=False)

    assert predictor.regression_validation["accepted"] is False
    assert predictor.regression_validation["status"] == "blocked_insufficient_dated_sample"
    assert predictor.regression_methods_by_team == {}
