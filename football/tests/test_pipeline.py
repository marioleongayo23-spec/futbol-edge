"""Tests de integración del pipeline (modo offline con datos de ejemplo)."""

import pytest

from futbol_pred.model import DixonColesModel
from futbol_pred.pipeline import (
    fit_model_from_fixtures,
    predict_match,
    run_pipeline,
    value_report,
)
from futbol_pred.ingest.api_football import ApiFootballClient


def test_pipeline_offline_corre_de_punta_a_punta():
    report = run_pipeline(league="laliga", demo=True)
    assert report["offline"] is True
    assert report["n_fixtures"] > 0
    assert report["sample_prediction"] is not None
    p = report["sample_prediction"]["1x2"]
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-2)


def test_modelo_ajusta_y_predice():
    fixtures = ApiFootballClient().get_fixtures("laliga")
    model = fit_model_from_fixtures(fixtures)
    assert model.fitted
    assert len(model.attack) >= 2
    teams = list(model.attack)
    pred = predict_match(model, teams[0], teams[1])
    assert pred.expected_goals[0] > 0


def test_equipo_desconocido_usa_prior_neutro():
    # Un recién ascendido sin histórico DEBE predecirse (prior neutro), no fallar.
    fixtures = ApiFootballClient().get_fixtures("laliga")
    model = fit_model_from_fixtures(fixtures)
    fuerte = max(model.attack, key=lambda t: model.attack[t])
    sm = model.predict_matrix(fuerte, "Equipo Ascendido")  # local fuerte
    p = sm.one_x_two()
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-6)
    assert not model.is_known("Equipo Ascendido")
    # El local fuerte en casa debe ser favorito frente a un desconocido medio.
    assert p["1"] > p["2"]


def test_value_report_formato():
    probs = {"1": 0.55, "X": 0.25, "2": 0.20}
    odds = {"1": 2.1, "X": 3.6, "2": 3.4}
    rep = value_report(probs, odds)
    assert isinstance(rep, list)
    if rep:
        assert {"market", "selection", "edge", "stake"} <= set(rep[0])
