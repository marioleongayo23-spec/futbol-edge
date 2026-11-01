from datetime import datetime, timedelta, timezone

from futbol_pred.dynamic_shadow_eval import evaluate_dynamic_shadow

BASE = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)


def historical_match(i, league="LaLiga", *, finished=True, snapshot=True):
    ko = BASE + timedelta(days=i)
    row = {
        "id": str(i), "league": league, "kickoff": ko.isoformat(),
        "home": "Home FC", "away": "Away FC",
        "finished": finished, "result": [2, 1] if finished else None,
    }
    if snapshot:
        row["prediction_history"] = [{
            "generated_at": (ko - timedelta(hours=4)).isoformat(),
            "probs": [52, 25, 23],
        }]
    return row


def test_readonly_challenger_evaluation_never_promotes():
    matches = [historical_match(i) for i in range(49)]
    report = evaluate_dynamic_shadow(matches, "LaLiga")
    assert report["league"] == "LaLiga"
    assert report["n"] >= 10
    assert report["promotion"] == "disabled"
    assert "log_loss" in report["shadow"]
    assert "rps" in report["delta_shadow_minus_published"]
    assert all(m["prediction_history"][0]["probs"] == [52, 25, 23] for m in matches)


def test_absent_snapshots_and_date_only_history_are_excluded():
    rows = [historical_match(i, snapshot=False) for i in range(39)]
    report = evaluate_dynamic_shadow(rows, "LaLiga")
    assert report["n"] == 0
    assert report["promotion"] == "disabled"
    rows = [historical_match(i) for i in range(38)]
    rows += [historical_match(38, finished=False)]
    rows[-2]["kickoff_precision"] = "date_only"
    assert evaluate_dynamic_shadow(rows, "LaLiga")["n"] > 0


def test_challenger_never_uses_another_leagues_future_results():
    rows = [historical_match(i) for i in range(43)]
    first = evaluate_dynamic_shadow(rows, "LaLiga")
    other_league = [historical_match(i, "Champions League") for i in range(50)]
    second = evaluate_dynamic_shadow(rows + other_league, "LaLiga")
    assert second == first
