import math

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


def test_challenger_pasa_si_mejora_ambas_metricas_frente_a_todos():
    candidate = {"log_loss": 0.97, "rps": 0.18}
    baselines = {
        "dixon_coles": {"log_loss": 1.01, "rps": 0.21},
        "elo": {"log_loss": 0.98, "rps": 0.19},
    }
    assert candidate_beats_all_baselines(candidate, baselines) is True


def test_challenger_no_pasa_si_empata_una_metrica():
    candidate = {"log_loss": 0.98, "rps": 0.18}
    baselines = {
        "dixon_coles": {"log_loss": 1.01, "rps": 0.21},
        "elo": {"log_loss": 0.98, "rps": 0.19},
    }
    assert candidate_beats_all_baselines(candidate, baselines) is False


def test_challenger_falla_cerrado_si_un_baseline_no_es_finito():
    candidate = {"log_loss": 0.97, "rps": 0.18}
    baselines = {
        "dixon_coles": {"log_loss": 1.01, "rps": 0.21},
        "elo": {"log_loss": math.nan, "rps": 0.19},
    }
    assert candidate_beats_all_baselines(candidate, baselines) is False


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
    assert result["acceptance_gate"]["rule"] == "strictly_better_than_every_baseline"
    assert 0.05 <= result["production"]["dc_weight"] <= 0.95


from futbol_pred.backtest.ensemble import blend3_probabilities, ensemble3_probabilities


def test_ensemble3_suma_uno_y_es_retrocompatible():
    dc = {"1": 0.5, "X": 0.3, "2": 0.2}
    elo = {"1": 0.45, "X": 0.30, "2": 0.25}
    pi = {"1": 0.55, "X": 0.25, "2": 0.20}
    p3 = ensemble3_probabilities(dc, elo, pi, 0.6, 0.5, 1.0)
    assert sum(p3.values()) == pytest.approx(1.0, abs=1e-9)
    # Si pi == elo, la mezcla de 3 vías coincide con la de 2 vías (mismo peso DC).
    b3 = blend3_probabilities(dc, elo, elo, dc_weight=0.7, rating_weight=0.5)
    from futbol_pred.backtest.ensemble import blend_probabilities
    b2 = blend_probabilities(dc, elo, 0.7)
    for k in ("1", "X", "2"):
        assert b3[k] == pytest.approx(b2[k], abs=1e-9)


def _records(probs_fn):
    """Genera registros walk-forward emparejables (round/home/away/actual/kickoff)."""
    recs = []
    outcomes = ["1", "X", "2"]
    for i in range(60):
        actual = outcomes[i % 3]
        recs.append({
            "round": (i // 10,), "home": f"H{i}", "away": f"A{i}",
            "actual": actual, "kickoff": float(i * 86400), "probs": probs_fn(actual),
        })
    return recs


def test_fit_ensemble_dispara_3way_con_pi_records():
    # pi "sabe" un poco más (más masa al resultado real) -> el 3-way es viable.
    dc = _records(lambda a: {"1": 0.4, "X": 0.3, "2": 0.3})
    elo = _records(lambda a: {"1": 0.34, "X": 0.33, "2": 0.33})
    pi = _records(lambda a: {**{"1": 0.3, "X": 0.3, "2": 0.3}, a: 0.5,
                             **{o: 0.25 for o in ("1", "X", "2") if o != a}})
    out = fit_walk_forward_ensemble(dc, elo, pi_records=pi)
    assert out is not None
    assert "3way" in out["method"]
    assert "pi_ratings" in out["production"]["components"]
    assert 0.0 <= out["production"]["rating_weight"] <= 1.0
    # Sin pi_records se mantiene el ensemble clásico de 2 vías.
    out2 = fit_walk_forward_ensemble(dc, elo)
    assert out2 is not None and "3way" not in out2["method"]
