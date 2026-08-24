import pytest

from futbol_pred.backtest.ensemble import (
    candidate_beats_all_baselines,
    ensemble_probabilities,
    fit_walk_forward_ensemble,
    temperature_scale,
)


def test_challenger_debe_superar_dc_y_elo():
    candidate = {"log_loss": 0.99, "rps": 0.20}
    baselines = {
        "dixon_coles": {"log_loss": 1.01, "rps": 0.21},
        "elo": {"log_loss": 0.98, "rps": 0.19},
    }
    assert candidate_beats_all_baselines(candidate, baselines) is False


def test_challenger_pasa_si_no_empeora_ningun_baseline():
    candidate = {"log_loss": 0.97, "rps": 0.18}
    baselines = {
        "dixon_coles": {"log_loss": 1.01, "rps": 0.21},
        "elo": {"log_loss": 0.98, "rps": 0.19},
    }
    assert candidate_beats_all_baselines(candidate, baselines) is True


def test_ensemble_suma_uno_y_respeta_extremos():
    probs = ensemble_probabilities(
        {"1": 0.60, "X": 0.25, "2": 0.15},
        {"1": 0.50, "X": 0.30, "2": 0.20},
        dc_weight=0.75,
    )
    assert sum(probs.values()) == pytest.approx(1.0)
    assert 0.50 < probs["1"] < 0.60


def test_temperatura_mayor_reduce_sobreconfianza():
    raw = {"1": 0.80, "X": 0.15, "2": 0.05}
    calibrated = temperature_scale(raw, 1.5)
    assert calibrated["1"] < raw["1"]


def test_ajuste_ensemble_reserva_validacion_temporal():
    dc, elo = [], []
    for i in range(60):
        actual = "1" if i % 3 else "X"
        base = {"1": 0.62, "X": 0.25, "2": 0.13}
        er = {"1": 0.52, "X": 0.31, "2": 0.17}
        common = {"round": ("league", "REGULAR", i), "home": f"H{i}", "away": f"A{i}", "actual": actual}
        dc.append({**common, "probs": base})
        elo.append({**common, "probs": er})
    result = fit_walk_forward_ensemble(dc, elo)
    assert result is not None
    assert result["n_validation"] > 0
    assert result["validation"]["n"] == result["n_validation"]
    assert isinstance(result["accepted"], bool)
    assert result["validation_baselines"]["dixon_coles"]["n"] == result["n_validation"]
    assert 0.05 <= result["production"]["dc_weight"] <= 0.95
