from futbol_pred.accuracy_detail import build_accuracy_details, enrich_accuracy


def _snapshot():
    return {
        "generated_at": "2026-08-24T18:00:00+02:00",
        "probs": [62, 23, 15],
        "stats": {
            "goals": {"home": 1.8, "away": 0.9, "total": 2.7},
            "shots": {"home": 13.0, "away": 9.0, "total": 22.0},
            "sot": {"home": 5.2, "away": 3.1, "total": 8.3},
            "corners": {"home": 6.0, "away": 4.0, "total": 10.0},
            "fouls": {"home": 12.0, "away": 14.0, "total": 26.0},
            "yellows": {"home": 2.0, "away": 3.0, "total": 5.0},
            "reds": {"home": 0.1, "away": 0.1, "total": 0.2},
        },
    }


def test_detalle_compara_snapshot_prepartido_con_stats_reales():
    match = {
        "id": "m1",
        "date": "2026-08-24",
        "kickoff": "2026-08-24T21:00:00+02:00",
        "home": "Local",
        "away": "Visitante",
        "finished": True,
        "result": [2, 1],
        "prediction_history": [_snapshot()],
        "statsRealSource": "API-Football · final",
        "statsRealUpdatedAt": "2026-08-24T23:15:00+02:00",
        "statsReal": {
            "goals": {"home": 2, "away": 1, "total": 3},
            "shots": {"home": 15, "away": 8, "total": 23},
            "sot": {"home": 6, "away": 2, "total": 8},
            "corners": {"home": 7, "away": 5, "total": 12},
            "fouls": {"home": 10, "away": 16, "total": 26},
            "yellows": {"home": 3, "away": 2, "total": 5},
            "reds": {"home": 0, "away": 1, "total": 1},
        },
    }

    rows = build_accuracy_details([match])

    assert len(rows) == 1
    row = rows[0]
    assert row["predicted_sign"] == "1"
    assert row["actual_sign"] == "1"
    assert row["hit_1x2"] is True
    assert row["stats_source"] == "API-Football · final"
    shots = next(item for item in row["stats"] if item["key"] == "shots")
    assert shots["predicted"]["total"] == 22.0
    assert shots["actual"]["total"] == 23.0
    assert shots["delta"]["total"] == 1.0
    assert shots["abs_error_total"] == 1.0
    reds = next(item for item in row["stats"] if item["key"] == "reds")
    assert reds["actual"]["total"] == 1.0


def test_sin_snapshot_prepartido_no_atribuye_acierto_a_posteriori():
    match = {
        "id": "m2",
        "finished": True,
        "result": [3, 0],
        "probs": [99, 1, 0],
        "statsReal": {"shots": {"home": 20, "away": 2, "total": 22}},
    }
    assert build_accuracy_details([match]) == []


def test_enrich_accuracy_conserva_agregado_y_anade_partidos():
    match = {
        "id": "m1",
        "date": "2026-08-24",
        "kickoff": "2026-08-24T21:00:00+02:00",
        "home": "Local",
        "away": "Visitante",
        "finished": True,
        "result": [2, 1],
        "prediction_history": [_snapshot()],
        "statsReal": {"shots": {"home": 15, "away": 8, "total": 23}},
    }
    aggregate = {"n_partidos": 1, "pct_1x2": 100, "metrics": []}
    enriched = enrich_accuracy(aggregate, [match])
    assert enriched["n_partidos"] == 1
    assert len(enriched["matches"]) == 1
