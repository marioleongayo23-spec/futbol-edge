from futbol_pred.feature_truth import build_feature_truth_table


def test_truth_table_expone_advanced_xg_y_movimiento_sin_promocion_automatica():
    payload = {
        "generated_at": "2026-09-07T12:00:00+02:00",
        "matches": [{
            "id": "m1",
            "home": "FC Barcelona",
            "away": "RCD Espanyol",
            "league": "LaLiga",
            "kickoff": "2026-09-07T21:00:00+02:00",
            "finished": False,
            "probs": [60, 23, 17],
            "model_meta": {
                "components": {"dixon_coles": {}, "elo": {}},
                "ensemble": {"accepted": False},
                "residual": {"accepted": False},
            },
            "market_history": [
                {"captured_at": "2026-09-07T09:00:00+02:00"},
                {"captured_at": "2026-09-07T11:00:00+02:00"},
            ],
            "advanced_stats": {
                "available_at": "2026-09-07T10:00:00+02:00",
                "status": "candidate_context_only",
                "affects_1x2": False,
            },
        }],
    }

    table = build_feature_truth_table(payload)
    rows = {row["feature"]: row for row in table["features"]}

    assert len(table["features"]) == 10
    assert rows["market_movement"]["coverage"]["pct"] == 100.0
    assert rows["market_movement"]["status"] == "challenger_collecting_evidence"
    assert "closing" in rows["market_movement"]["notes"]
    assert rows["advanced_xg_goalkeeper"]["coverage"]["pct"] == 100.0
    assert rows["advanced_xg_goalkeeper"]["status"] == "candidate_context_only"
    assert rows["advanced_xg_goalkeeper"]["available_at"] == "2026-09-07T10:00:00+02:00"
