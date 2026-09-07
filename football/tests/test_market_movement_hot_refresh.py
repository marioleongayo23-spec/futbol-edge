from datetime import datetime

from futbol_pred.matchday_market_refresh import _apply_market


def test_hot_refresh_construye_movimiento_solo_con_capturas_prepartido():
    match = {
        "id": "m-live",
        "kickoff": "2026-09-07T21:00:00+02:00",
        "model_probs": [45.0, 30.0, 25.0],
        "probs": [45, 30, 25],
        "markets": {"over_2_5": 0.52},
        "market_calibration": {"model_weight": 0.7, "temperature": 1.0},
        "value": [],
    }
    first = {
        "1x2": {"1": 2.10, "X": 3.40, "2": 3.70},
        "source_updated_at": "2026-09-07T16:55:00+02:00",
    }
    second = {
        "1x2": {"1": 1.90, "X": 3.55, "2": 4.10},
        "source_updated_at": "2026-09-07T17:55:00+02:00",
    }

    assert _apply_market(match, first, datetime.fromisoformat("2026-09-07T17:00:00+02:00"), 30) is True
    assert len(match["market_history"]) == 1
    assert "market_movement" not in match

    assert _apply_market(match, second, datetime.fromisoformat("2026-09-07T18:00:00+02:00"), 30) is True
    assert len(match["market_history"]) == 2
    assert match["market_movement"]["n_snapshots"] == 2
    assert match["market_movement"]["to"] < match["kickoff"]
