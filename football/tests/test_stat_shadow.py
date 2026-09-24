from datetime import datetime

import futbol_pred.prediction_snapshots as snapshots
from futbol_pred.stat_shadow import SHADOW_METHOD, build_stat_shadow


def _evaluation(n=24):
    return {
        "schema": "truth-evaluation-v1",
        "updated_at": "2026-09-06T23:00:00+00:00",
        "summary": {
            "by_stat": {
                "fouls": {
                    "n": n,
                    "bias_predicted_minus_actual": {"home": 2.0, "away": -1.0, "total": 1.0},
                },
                "yellows": {
                    "n": n,
                    "bias_predicted_minus_actual": {"home": 0.8, "away": 0.4, "total": 1.2},
                },
            },
            "by_league": {},
        },
    }


def _match():
    return {
        "id": "m1",
        "league": "LaLiga",
        "date": "2026-09-08",
        "kickoff": "2026-09-08T21:00:00+02:00",
        "home": "Barcelona",
        "away": "Valencia",
        "probs": [60, 24, 16],
        "model_meta": {"version": "edge-test"},
        "stats": {
            "fouls": {"home": 12.0, "away": 14.0, "total": 26.0},
            "yellows": {"home": 2.5, "away": 3.0, "total": 5.5},
            "shots": {"home": 15.0, "away": 9.0, "total": 24.0},
        },
    }


def test_shadow_corrige_sesgo_con_shrinkage_sin_mutar_match():
    match = _match()
    before = {key: dict(value) for key, value in match["stats"].items()}
    shadow = build_stat_shadow(match, evaluation=_evaluation())

    assert shadow["schema"] == "stat-shadow-v1"
    assert shadow["affects_production"] is False
    assert shadow["affects_1x2"] is False
    assert shadow["automatic_production_promotion"] is False
    assert set(shadow["stats"]) == {"fouls", "yellows"}
    assert shadow["stats"]["fouls"][SHADOW_METHOD]["home"] < 12.0
    assert shadow["stats"]["fouls"][SHADOW_METHOD]["away"] > 14.0
    assert shadow["stats"]["fouls"]["training"]["scope"] == "global"
    assert match["stats"] == before


def test_shadow_no_inventa_muestra_insuficiente():
    assert build_stat_shadow(_match(), evaluation=_evaluation(n=10)) is None


def test_snapshot_archiva_shadow_pero_no_lo_convierte_en_campo_de_serving(monkeypatch):
    marker = {
        "schema": "stat-shadow-v1",
        "stats": {"fouls": {"published": {"home": 12, "away": 14, "total": 26}}},
        "affects_production": False,
        "affects_1x2": False,
        "automatic_production_promotion": False,
    }
    monkeypatch.setattr(snapshots, "build_stat_shadow", lambda match: marker)
    match = _match()
    snap = snapshots._snapshot(match, datetime.fromisoformat("2026-09-07T12:00:00+02:00"), "T-24h")

    assert snap["stat_challengers"] == marker
    assert "stat_challengers" not in match
    assert "stat_challengers" not in snapshots._SNAPSHOT_FIELDS
