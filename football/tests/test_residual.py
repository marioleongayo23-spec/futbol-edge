import pytest

from futbol_pred.backtest.residual import (
    MIN_RECORDS, fit_walk_forward_residual, residual_probabilities,
)


def _records(n):
    dc, elo = [], []
    for index in range(n):
        actual = ("1", "X", "2")[index % 3]
        dc_probs = {"1": 0.50, "X": 0.28, "2": 0.22}
        elo_probs = {
            "1": 0.62 if actual == "1" else 0.24,
            "X": 0.52 if actual == "X" else 0.22,
            "2": 0.58 if actual == "2" else 0.20,
        }
        total = sum(elo_probs.values())
        elo_probs = {key: value / total for key, value in elo_probs.items()}
        common = {
            "round": ("liga", "REGULAR", index), "home": f"H{index}",
            "away": f"A{index}", "actual": actual,
        }
        dc.append({**common, "probs": dc_probs})
        elo.append({**common, "probs": elo_probs})
    return dc, elo


def test_residual_se_bloquea_sin_muestra_suficiente():
    dc, elo = _records(MIN_RECORDS - 1)
    report = fit_walk_forward_residual(dc, elo)
    assert report["accepted"] is False
    assert report["status"] == "blocked_insufficient_sample"


def test_residual_reserva_cola_temporal_y_publica_gate():
    dc, elo = _records(120)
    report = fit_walk_forward_residual(dc, elo)
    assert report["n_train"] + report["n_validation"] == 120
    assert report["n_validation"] >= 20
    assert report["acceptance_gate"]["metrics"] == ["log_loss", "rps"]
    assert isinstance(report["accepted"], bool)
    assert report["production"]["converged"] is True


def test_residual_suma_uno_y_falla_cerrado_a_dixon_coles():
    dc = {"1": 0.5, "X": 0.3, "2": 0.2}
    elo = {"1": 0.4, "X": 0.32, "2": 0.28}
    assert residual_probabilities(dc, elo, {}) == pytest.approx(dc)
    params = {
        "weights": [[0] * 6 for _ in range(3)],
        "feature_mean": [0] * 5, "feature_scale": [1] * 5,
    }
    output = residual_probabilities(dc, elo, params)
    assert sum(output.values()) == pytest.approx(1.0)
    assert output == pytest.approx(dc)
