from futbol_pred.stat_shadow import SHADOW_METHOD
from futbol_pred.stat_shadow_evaluation import build_observations, update_archive, empty_archive


def _truth():
    return {
        "schema": "final-stats-truth-v1",
        "matches": {
            "truth-1": {
                "league": "laliga",
                "season": 2026,
                "date": "2026-09-08",
                "home": "Barcelona",
                "away": "Valencia",
                "consensus": {
                    "fouls": {
                        "status": "single_source",
                        "usable": True,
                        "home": 10,
                        "away": 12,
                        "sources": ["football_data_uk"],
                        "confidence": 0.6,
                    },
                    "yellows": {
                        "status": "single_source",
                        "usable": True,
                        "home": 2,
                        "away": 3,
                        "sources": ["football_data_uk"],
                        "confidence": 0.6,
                    },
                },
            }
        },
    }


def _dashboard(with_shadow=True):
    snapshot = {
        "generated_at": "2026-09-08T18:00:00+02:00",
        "window": "T-3h",
        "model_version": "edge-test",
        "stats": {
            "fouls": {"home": 12, "away": 14, "total": 26},
            "yellows": {"home": 3, "away": 4, "total": 7},
        },
    }
    if with_shadow:
        snapshot["stat_challengers"] = {
            "schema": "stat-shadow-v1",
            "stats": {
                "fouls": {
                    "published": {"home": 12, "away": 14, "total": 26},
                    SHADOW_METHOD: {"home": 10, "away": 12, "total": 22},
                    "training": {"n": 24, "scope": "global"},
                },
                "yellows": {
                    "published": {"home": 3, "away": 4, "total": 7},
                    SHADOW_METHOD: {"home": 2, "away": 3, "total": 5},
                    "training": {"n": 24, "scope": "global"},
                },
            },
            "affects_production": False,
            "affects_1x2": False,
            "automatic_production_promotion": False,
        }
    return [{
        "id": "m1",
        "league": "LaLiga",
        "date": "2026-09-08",
        "kickoff": "2026-09-08T21:00:00+02:00",
        "home": "Barcelona",
        "away": "Valencia",
        "finished": True,
        "prediction_history": [snapshot],
    }]


def test_shadow_eval_usa_solo_snapshot_prepartido_y_verdad_utilizable():
    observations, audit = build_observations(_dashboard(), _truth())
    assert len(observations) == 1
    fouls = observations[0]["stats"]["fouls"]["methods"]
    assert fouls["published"]["absolute_error"]["total"] == 4
    assert fouls[SHADOW_METHOD]["absolute_error"]["total"] == 0
    assert audit["shadow_observations"] == 1
    assert observations[0]["affects_1x2"] is False


def test_shadow_eval_no_reconstruye_challenger_si_snapshot_no_lo_tenia():
    observations, audit = build_observations(_dashboard(with_shadow=False), _truth())
    assert observations == []
    assert audit["missing_shadow_snapshot"] == 1


def test_gate_recomienda_solo_tras_80_observaciones_prospectivas():
    base_obs, _ = build_observations(_dashboard(), _truth())
    template = base_obs[0]

    few = []
    for i in range(20):
        row = {**template, "match_id": f"few-{i}", "date": f"2026-09-{(i % 20) + 1:02d}"}
        few.append(row)
    archive, report = update_archive(empty_archive(), few, updated_at="2026-10-01T00:00:00Z", audit={})
    gate = report["recommendations"]["laliga"]["fouls"]
    assert gate["status"] == "collecting_prospective_sample"
    assert gate["recommended"] is False
    assert report["automatic_production_promotion"] is False

    many = []
    for i in range(80):
        row = {**template, "match_id": f"many-{i}", "date": f"2026-{9 + (i // 28):02d}-{(i % 28) + 1:02d}"}
        many.append(row)
    archive2, report2 = update_archive(empty_archive(), many, updated_at="2026-12-01T00:00:00Z", audit={})
    gate2 = report2["recommendations"]["laliga"]["fouls"]
    assert gate2["status"] == "recommendation_ready"
    assert gate2["recommended"] is True
    assert gate2["n"] == 80
    assert report2["affects_1x2"] is False
    assert archive2["automatic_production_promotion"] is False
