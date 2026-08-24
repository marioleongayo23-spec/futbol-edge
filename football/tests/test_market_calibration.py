from futbol_pred.market_calibration import learn_market_calibration


def test_calibracion_mercado_necesita_muestra_minima():
    assert learn_market_calibration([], "LaLiga") is None


def test_calibracion_mercado_usa_solo_snapshots_prepartido():
    matches = []
    for i in range(45):
        result = [2, 0] if i % 3 else [1, 1]
        snapshot = {
            "generated_at": f"2026-01-{(i % 28) + 1:02d}T10:00:00+01:00",
            "model_probs": [58, 28, 14],
            "odds": {"1x2": {"fair": {"1": 0.55, "X": 0.29, "2": 0.16}}},
        }
        matches.append({
            "league": "LaLiga",
            "finished": True,
            "result": result,
            "kickoff": f"2026-02-{(i % 28) + 1:02d}T20:00:00+01:00",
            "prediction_history": [snapshot],
        })
    result = learn_market_calibration(matches, "LaLiga")
    assert result is not None and result["n"] == 45
    assert isinstance(result["accepted"], bool)
    assert 0.05 <= result["production"]["model_weight"] <= 0.95
