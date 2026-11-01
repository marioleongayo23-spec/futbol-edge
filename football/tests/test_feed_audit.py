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


def test_bootstrap_uses_match_days_and_is_deterministic():
    from futbol_pred.feed_audit import _block_bootstrap
    champion = {"1": 0.6, "X": 0.2, "2": 0.2}
    baseline = {"1": 0.45, "X": 0.3, "2": 0.25}
    rows = [(f"2026-09-{(i % 20) + 1:02d}", champion, baseline, "1") for i in range(40)]
    a = _block_bootstrap(rows)
    assert a == _block_bootstrap(rows)
    assert a["n_days"] == 20
    assert a["delta_log_loss_ci95"][1] < 0
    assert a["delta_rps_ci95"][1] < 0
    assert _block_bootstrap(rows[:10]) is None


def test_audit_explains_historical_missing_snapshots_without_backfilling():
    missing = _match("no-snap", [2, 0], "2026-09-20T12:00:00+02:00", [55, 25, 20])
    missing.pop("prediction_history")
    late = _match("late", [1, 0], "2026-09-20T20:05:00+02:00", [55, 25, 20])
    invalid = _match("invalid", [1, 0], "2026-09-20T12:00:00+02:00", [100, 100, 100])
    group = audit_payload({"matches": [missing, late, invalid]})["leagues"]["LaLiga"]
    assert group["finished_without_valid_snapshot"] == 3
    assert group["missing_snapshot_reasons"] == {
        "no_snapshots_preserved": 1,
        "captured_only_after_kickoff": 1,
        "pre_kickoff_probs_invalid": 1,
    }


def test_audit_highlights_upcoming_fixtures_without_a_pre_match_capture():
    with_snapshot = _match("ready", [1, 0], "2026-09-20T12:00:00+02:00", [55, 25, 20])
    with_snapshot["finished"] = False
    with_snapshot.pop("result")
    missing = {**with_snapshot, "id": "pending", "prediction_history": []}
    group = audit_payload({
        "generated_at": "2026-09-20T18:00:00+02:00",
        "matches": [with_snapshot, missing],
    })["leagues"]["LaLiga"]
    assert group["upcoming_48h"] == 2
    assert group["upcoming_48h_without_snapshot"] == 1
