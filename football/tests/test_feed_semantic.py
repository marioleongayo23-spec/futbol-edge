from futbol_pred.feed_semantic import semantic_digest, semantic_feed


def _feed():
    return {
        "schema_version": 7,
        "generated_at": "2026-08-25T10:15:00+02:00",
        "market_calibration": {"laliga": {"accepted": True}},
        "matches": [
            {
                "id": "match-1",
                "updatedAt": "2026-08-25T10:15:00+02:00",
                "status": "SCHEDULED",
                "probs": [45, 30, 25],
                "odds": {"1": 2.1, "X": 3.2, "2": 3.8},
            }
        ],
    }


def test_timestamp_de_generacion_no_cambia_la_huella():
    first = _feed()
    second = _feed()
    second["generated_at"] = "2026-08-25T10:30:00+02:00"
    second["matches"][0]["updatedAt"] = "2026-08-25T10:30:00+02:00"

    assert semantic_digest(first) == semantic_digest(second)


def test_cambio_real_en_cuota_si_cambia_la_huella():
    first = _feed()
    second = _feed()
    second["matches"][0]["odds"]["1"] = 2.2

    assert semantic_digest(first) != semantic_digest(second)


def test_cambio_real_en_resultado_si_cambia_la_huella():
    first = _feed()
    second = _feed()
    second["matches"][0].update({"finished": True, "result": [2, 1]})

    assert semantic_digest(first) != semantic_digest(second)


def test_no_elimina_timestamps_de_snapshots_reales():
    feed = _feed()
    feed["matches"][0]["closing_odds"] = {
        "captured_at": "2026-08-25T18:00:00+02:00",
        "is_real": True,
        "1x2": {"1": 2.0, "X": 3.3, "2": 4.0},
    }

    normalized = semantic_feed(feed)
    assert normalized["matches"][0]["closing_odds"]["captured_at"] == "2026-08-25T18:00:00+02:00"
