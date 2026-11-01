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


def test_snapshots_posteriores_al_saque_no_cuentan_como_finales():
    initial = _snapshot("initial", "2026-08-24T12:00:00+02:00", [40, 30, 30])
    future = _snapshot("final_T-60_official", "2026-08-24T21:05:00+02:00", [100, 0, 0])
    ten = _snapshot("10:15", "2026-08-24T22:00:00+02:00", [100, 0, 0])
    match = {
        "league": "LaLiga", "finished": True, "result": [2, 0],
        "kickoff": "2026-08-24T21:00:00+02:00",
        "prediction_history": [initial, future, ten],
        "prediction_snapshot": future,
    }
    report = build_performance([match])
    stages = {s["key"]: s for s in report["betting_window_quality"]["stages"]}
    assert "initial" in stages
    assert "final" not in stages
    assert report["initial_vs_10_15"] is None
    assert report["probability_quality"]["published"]["n"] == 1


def test_roi_omite_cuotas_infinita_y_seleccion_no_valida():
    snapshot = _snapshot("initial", "2026-08-24T12:00:00+02:00", [55, 25, 20])
    snapshot["value"] = [
        {"market": "1x2", "selection": "1", "edge": 0.3, "odds": float("inf")},
        {"market": "ou25", "selection": "invalid", "edge": 0.3, "odds": 3},
        {"market": "1x2", "selection": "X", "edge": float("nan"), "odds": 3},
    ]
    match = {
        "league": "LaLiga", "finished": True, "result": [1, 0],
        "kickoff": "2026-08-24T21:00:00+02:00",
        "prediction_history": [snapshot],
    }
    report = build_performance([match])
    assert report["overall"]["n"] == 0
    assert report["overall"]["roi"] is None


def test_calidad_no_puntua_vector_de_probabilidades_no_finito():
    match = {
        "league": "LaLiga", "finished": True, "result": [1, 0],
        "kickoff": "2026-08-24T21:00:00+02:00",
        "prediction_history": [_snapshot(
            "initial", "2026-08-24T12:00:00+02:00", [float("nan"), 30, 70]
        )],
    }
    assert build_performance([match]) is None
