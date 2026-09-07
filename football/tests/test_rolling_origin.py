from __future__ import annotations

from futbol_pred.backtest.rolling import paired_rolling_comparison, rolling_origin_report


def _record(day: int, index: int, probs: dict[str, float], actual: str = "1") -> dict:
    return {
        "round": ("laliga", "REGULAR", 2026, day),
        "kickoff": float(day * 86_400 + index * 3_600),
        "home": f"H{day}-{index}",
        "away": f"A{day}-{index}",
        "actual": actual,
        "probs": probs,
    }


def test_rolling_origin_reports_round_cumulative_and_trailing_windows():
    records = []
    for day in range(1, 9):
        records.append(_record(day, 0, {"1": 0.62, "X": 0.22, "2": 0.16}))
        records.append(_record(day, 1, {"1": 0.58, "X": 0.24, "2": 0.18}))

    report = rolling_origin_report(records, trailing_rounds=5)

    assert report["method"] == "rolling-origin-by-round-v1"
    assert report["n_rounds"] == 8
    assert report["n_predictions"] == 16
    assert report["trailing_rounds"] == 5
    assert report["rounds"][0]["cumulative"]["n"] == 2
    assert report["rounds"][-1]["cumulative"]["n"] == 16
    assert report["rounds"][-1]["trailing"]["n"] == 10
    assert report["latest"]["round"][-1] == 8
    assert report["stability"]["status"] == "stable"


def test_rolling_origin_marks_recent_dual_metric_degradation():
    records = []
    # Primeras 8 jornadas: modelo muy bueno. Últimas 5: muy confiado en el signo
    # equivocado. La ventana reciente debe degradar tanto log-loss como RPS.
    for day in range(1, 14):
        if day <= 8:
            probs, actual = {"1": 0.78, "X": 0.14, "2": 0.08}, "1"
        else:
            probs, actual = {"1": 0.78, "X": 0.14, "2": 0.08}, "2"
        records.append(_record(day, 0, probs, actual=actual))

    report = rolling_origin_report(records, trailing_rounds=5)

    assert report["stability"]["status"] == "degrading"
    deltas = report["stability"]["recent_vs_cumulative_delta"]
    assert deltas["log_loss"] > 0.10
    assert deltas["rps"] > 0.10
    assert report["stability"]["round_log_loss_std"] > 0
    assert report["stability"]["round_rps_std"] > 0


def test_paired_comparison_uses_only_identical_match_sample():
    candidate = []
    baseline = []
    for day in range(1, 7):
        candidate.append(_record(day, 0, {"1": 0.70, "X": 0.20, "2": 0.10}))
        baseline.append(_record(day, 0, {"1": 0.50, "X": 0.30, "2": 0.20}))
    # Baseline extra: no puede aumentar artificialmente su muestra emparejada.
    baseline.append(_record(99, 0, {"1": 0.99, "X": 0.005, "2": 0.005}))

    report = paired_rolling_comparison(candidate, baseline, trailing_rounds=5)

    assert report["coverage"]["candidate"] == 6
    assert report["coverage"]["baseline"] == 7
    assert report["coverage"]["paired"] == 6
    assert report["coverage"]["same_sample_only"] is True
    assert report["n_rounds"] == 6
    assert report["rounds_won_both"] == 6
    assert report["round_win_rate_both"] == 1.0
    assert report["status"] == "candidate_ahead_and_stable"
    assert report["promotion_gate"] is False


def test_paired_comparison_never_pairs_same_teams_with_different_actual_result():
    candidate = [_record(1, 0, {"1": 0.70, "X": 0.20, "2": 0.10}, actual="1")]
    baseline = [_record(1, 0, {"1": 0.50, "X": 0.30, "2": 0.20}, actual="2")]

    report = paired_rolling_comparison(candidate, baseline)

    assert report["coverage"]["paired"] == 0
    assert report["n_rounds"] == 0
    assert report["round_win_rate_both"] is None
