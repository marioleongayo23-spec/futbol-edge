from futbol_pred.feature_truth import build_feature_truth_table, refresh_payload


def _match(**updates):
    row = {
        "id": "m1",
        "home": "A",
        "away": "B",
        "league": "LaLiga",
        "kickoff": "2026-08-28T21:30:00+02:00",
        "status": "SCHEDULED",
        "finished": False,
        "probs": [45, 30, 25],
        "model_meta": {
            "components": {
                "dixon_coles": {"1": 0.45, "X": 0.30, "2": 0.25},
                "elo": {"1": 0.42, "X": 0.31, "2": 0.27},
            },
            "ensemble": {"accepted": True},
            "residual": {"accepted": False},
        },
        "stats": {"shots": {"home": 12, "away": 9, "total": 21}},
    }
    row.update(updates)
    return row


def test_truth_table_reports_dynamic_coverage_and_timestamps():
    payload = {
        "generated_at": "2026-08-28T11:30:00+02:00",
        "matches": [
            _match(
                odds={
                    "1x2": {"odds": {"1": 2.1, "X": 3.3, "2": 3.5}},
                    "meta": {"source_updated_at": "2026-08-28T11:20:00+02:00"},
                },
                weather={
                    "source_updated_at": "2026-08-28T11:10:00+02:00",
                    "forecast_for": "2026-08-28T21:00:00+02:00",
                },
                alineacion={
                    "source_updated_at": "2026-08-28T11:25:00+02:00",
                    "clave_local": [{"jugador": "Uno"}],
                    "clave_visitante": [{"jugador": "Dos"}],
                },
                tactical_matchup={"tempo": "alto"},
            ),
            _match(id="m2", home="C", away="D"),
        ],
    }

    table = build_feature_truth_table(payload)
    by_feature = {row["feature"]: row for row in table["features"]}

    assert table["eligible_matches"] == 2
    assert by_feature["dixon_coles_score_model"]["coverage"]["pct"] == 100.0
    assert by_feature["market_odds"]["coverage"]["pct"] == 50.0
    assert by_feature["market_odds"]["available_at"] == "2026-08-28T11:20:00+02:00"
    assert by_feature["weather_forecast"]["coverage"]["pct"] == 50.0
    assert "1x2" not in by_feature["weather_forecast"]["uses"]
    assert by_feature["lineups_absences_minutes"]["leakage_risk"] == "high_until_snapshot_gate"
    assert by_feature["player_props"]["coverage"]["pct"] == 50.0
    assert by_feature["elo"]["status"] == "production_gated"


def test_refresh_payload_is_idempotent():
    payload = {"generated_at": "2026-08-28T11:30:00+02:00", "matches": [_match()]}
    assert refresh_payload(payload) is True
    first = payload["feature_truth_table"]
    assert refresh_payload(payload) is False
    assert payload["feature_truth_table"] == first
