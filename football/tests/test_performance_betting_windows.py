from futbol_pred.performance import build_performance


def _snapshot(window, generated_at, probs):
    return {"window": window, "generated_at": generated_at, "probs": probs, "model_probs": probs}


def test_rendimiento_compara_versiones_reales_de_apuesta():
    matches = []
    samples = [
        ([2, 0], [45, 30, 25], [55, 27, 18], [62, 24, 14], "final_T-60_official"),
        ([0, 1], [40, 30, 30], [33, 29, 38], [28, 27, 45], "final_T-30_official"),
        ([1, 1], [45, 25, 30], [34, 38, 28], [30, 44, 26], "final_T-60_official"),
    ]
    for index, (result, initial, prefinal, final, final_window) in enumerate(samples):
        history = [
            _snapshot("initial", f"2026-08-2{index}T12:00:00+02:00", initial),
            _snapshot("pre_final_T-3h", f"2026-08-2{index}T18:00:00+02:00", prefinal),
            _snapshot(final_window, f"2026-08-2{index}T20:00:00+02:00", final),
        ]
        matches.append({
            "id": f"m{index}", "league": "LaLiga", "finished": True, "result": result,
            "kickoff": f"2026-08-2{index}T21:00:00+02:00",
            "prediction_history": history, "prediction_snapshot": history[-1],
        })

    report = build_performance(matches)
    windows = report["betting_window_quality"]
    by_key = {row["key"]: row for row in windows["stages"]}
    assert set(by_key) >= {"initial", "pre_final", "final"}
    assert by_key["pre_final"]["quality"]["n"] == 3
    assert by_key["final"]["quality"]["n"] == 3
    assert by_key["final"]["vs_initial"]["log_loss_delta"] < 0
    assert by_key["final"]["vs_initial"]["rps_delta"] < 0
    assert windows["final_window_counts"] == {"final_T-60_official": 2, "final_T-30_official": 1}
