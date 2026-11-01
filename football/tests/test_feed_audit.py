"""Regression tests for the read-only, real-data calibration audit."""
from futbol_pred.feed_audit import audit_payload


def _match(mid, result, generated, probs, model=None, market=None):
    snap = {
        "generated_at": generated, "probs": probs,
        "model_probs": model,
        "odds": {"1x2": {"fair": market}} if market is not None else {},
    }
    return {
        "id": mid, "home": "A", "away": "B", "league": "LaLiga",
        "kickoff": "2026-09-20T20:00:00+02:00",
        "finished": True, "result": result,
        "prediction_history": [snap],
    }


def test_audit_uses_only_pre_kickoff_observations():
    before = _match("a", [1, 0], "2026-09-20T12:00:00+02:00",
                    [55, 25, 20], [50, 28, 22],
                    {"1": 0.45, "X": 0.29, "2": 0.26})
    after = _match("b", [0, 1], "2026-09-20T20:05:00+02:00",
                   [0, 0, 100], [0, 0, 100],
                   {"1": 0.1, "X": 0.1, "2": 0.8})
    group = audit_payload({"matches": [before, after]})["leagues"]["LaLiga"]
    assert group["finished"] == 2
    assert group["finished_with_snapshot"] == 1
    assert group["finished_without_valid_snapshot"] == 1
    assert group["probability_quality"]["published"]["n"] == 1
    assert group["published_vs_model_paired"]["n"] == 1
    assert group["published_vs_market_paired"]["n"] == 1
    assert group["published_vs_market_paired"]["preliminary"] is True


def test_audit_rejects_nonfinite_values_and_reports_no_fabricated_samples():
    bad = _match("a", [2, 1], "2026-09-20T12:00:00+02:00",
                 [float("nan"), 20, 80])
    bad2 = _match("b", [2, 1], "2026-09-20T12:00:00+02:00",
                  [55, 25, 20], model=[100, 100, 100],
                  market={"1": float("inf"), "X": 0.3, "2": 0.7})
    group = audit_payload({"matches": [bad, bad2]})["leagues"]["LaLiga"]
    assert group["finished_with_snapshot"] == 1
    assert group["probability_quality"]["published"]["n"] == 1
    assert group["probability_quality"]["model"] is None
    assert group["probability_quality"]["market"] is None
    assert group["published_vs_market_paired"] is None


def test_audit_splits_competitions_and_does_not_score_unfinished_results():
    future = {"league": "Champions League", "id": "c", "finished": False,
              "probs": [60, 25, 15], "result": [0, 0]}
    report = audit_payload({"matches": [future]})
    assert report["status"] == "ok"
    league = report["leagues"]["Champions League"]
    assert league["finished"] == 0
    assert league["future_with_valid_prediction"] == 1
    assert league["probability_quality"]["published"] is None
    assert audit_payload({"matches": None})["status"] == "invalid_feed"
