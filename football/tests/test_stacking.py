"""Meta-modelo de stacking log-lineal."""

import pytest

from futbol_pred.backtest.stacking import (
    _stack_probs,
    fit_walk_forward_stack,
)


def test_stack_probs_suma_uno_y_pesos_iguales_es_pool_geometrico():
    per_model = {
        "a": {"1": 0.5, "X": 0.3, "2": 0.2},
        "b": {"1": 0.4, "X": 0.35, "2": 0.25},
    }
    p = _stack_probs(per_model, {"a": 0.5, "b": 0.5})
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-9)
    # Peso 0 en un modelo -> el otro manda (normalizado).
    only_a = _stack_probs(per_model, {"a": 1.0, "b": 0.0})
    assert only_a["1"] > only_a["2"]


def _records(name_bias):
    recs = []
    outcomes = ["1", "X", "2"]
    for i in range(80):
        actual = outcomes[i % 3]
        base = {"1": 0.33, "X": 0.33, "2": 0.34}
        # name_bias añade algo de masa al resultado real (modelo "informado").
        probs = dict(base)
        probs[actual] = probs[actual] + name_bias
        s = sum(probs.values())
        probs = {k: v / s for k, v in probs.items()}
        recs.append({"round": (i // 10,), "home": f"H{i}", "away": f"A{i}",
                     "actual": actual, "kickoff": float(i * 86400), "probs": probs})
    return recs


def test_fit_stack_devuelve_estructura_y_gate():
    records = {
        "dixon_coles": _records(0.20),
        "elo": _records(0.05),
        "pi_ratings": _records(0.12),
    }
    out = fit_walk_forward_stack(records)
    assert out is not None
    assert out["method"] == "walk-forward-log-linear-stack"
    assert set(out["production"]["weights"]) == {"dixon_coles", "elo", "pi_ratings"}
    assert "accepted" in out and isinstance(out["accepted"], bool)
    assert out["validation"]["n"] > 0


def test_fit_stack_none_con_pocos_datos():
    records = {"a": _records(0.1)[:10], "b": _records(0.1)[:10]}
    assert fit_walk_forward_stack(records) is None
