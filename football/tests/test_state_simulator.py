import pytest

from futbol_pred.model.state_simulator import simulate_match_states
from futbol_pred.operational import attach_state_simulations


def test_simulador_es_reproducible_y_las_probabilidades_suman_uno():
    first = simulate_match_states(1.7, 1.0, seed="partido-1", simulations=2500)
    second = simulate_match_states(1.7, 1.0, seed="partido-1", simulations=2500)
    assert first == second
    assert sum(first["probabilities"].values()) == pytest.approx(1.0, abs=1e-4)
    assert first["total_goals_range_80"][0] <= first["total_goals_range_80"][1]


def test_calor_reduce_ritmo_esperado_sin_tocar_prediccion_publicada():
    neutral = simulate_match_states(1.5, 1.2, seed="igual", temperature_c=18, simulations=5000)
    hot = simulate_match_states(1.5, 1.2, seed="igual", temperature_c=36, simulations=5000)
    assert hot["assumptions"]["pace_multiplier"] < 1
    assert hot["expected_total_goals"] < neutral["expected_total_goals"]
    match = {
        "id": "m1", "finished": False, "xg": [1.5, 1.2], "probs": [45, 29, 26],
        "weather": {"temperature_c": 36}, "stats": {"yellows": {"total": 5}},
    }
    assert attach_state_simulations([match]) == 1
    assert match["probs"] == [45, 29, 26]
    assert match["state_simulation"]["status"] == "scenario_only_not_in_1x2"


def test_desglose_marcadores_exactos_y_margenes():
    """El simulador ahora desglosa marcadores exactos y márgenes de victoria,
    ambos derivados del mismo Monte Carlo (los márgenes suman 1)."""
    from futbol_pred.model.state_simulator import simulate_match_states
    s = simulate_match_states(1.8, 1.0, seed="margin", simulations=6000)
    assert s["exact_scores"] and all("-" in e["score"] and e["probability"] > 0 for e in s["exact_scores"])
    # ordenados de más a menos probable
    probs = [e["probability"] for e in s["exact_scores"]]
    assert probs == sorted(probs, reverse=True)
    wm = s["winning_margins"]
    assert abs(sum(wm.values()) - 1.0) < 1e-6
    # el local es favorito (1.8 vs 1.0): gana por 1 más que pierde por 1
    assert wm["home_by_1"] > wm["away_by_1"]
