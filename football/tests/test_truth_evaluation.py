import json

from futbol_pred.final_stats_truth import SCHEMA as TRUTH_SCHEMA
from futbol_pred.truth_evaluation import (
    SCHEMA,
    build_observations,
    empty_archive,
    refresh_truth_evaluation,
    update_archive,
)


def _snapshot(generated_at="2026-08-20T18:00:00+02:00"):
    return {
        "generated_at": generated_at,
        "window": "pre_final_T-3h",
        "model_version": "edge-test",
        "probs": [62, 23, 15],
        "xg": [2.0, 0.8],
        "stats": {
            "goals": {"home": 2.0, "away": 0.8, "total": 2.8},
            "shots": {"home": 13.0, "away": 9.0, "total": 22.0},
            "sot": {"home": 5.0, "away": 3.0, "total": 8.0},
            "fouls": {"home": 12.0, "away": 14.0, "total": 26.0},
        },
    }


def _match(snapshot=None, *, home="FC Barcelona", away="RCD Espanyol"):
    return {
        "id": "m1",
        "league": "LaLiga",
        "season": 2026,
        "date": "2026-08-20",
        "kickoff": "2026-08-20T21:00:00+02:00",
        "home": home,
        "away": away,
        "finished": True,
        "result": [2, 1],
        "prediction_history": [snapshot or _snapshot()],
    }


def _truth(*, shots_home=15, xg_home=2.1, xg_usable=True):
    return {
        "schema": TRUTH_SCHEMA,
        "matches": {
            "truth-match-1": {
                "match_id": "truth-match-1",
                "league": "laliga",
                "season": 2026,
                "date": "2026-08-20",
                "home": "Barcelona",
                "away": "Espanol",
                "status": "verified_multi_source",
                "consensus": {
                    "shots": {
                        "status": "agreed",
                        "usable": True,
                        "home": shots_home,
                        "away": 8,
                        "sources": ["api_football", "football_data_uk"],
                        "confidence": 1.0,
                    },
                    "xg": {
                        "status": "single_source" if xg_usable else "conflict",
                        "usable": xg_usable,
                        "home": xg_home,
                        "away": 0.9,
                        "sources": ["api_football"],
                        "confidence": 0.6 if xg_usable else 0.0,
                    },
                    "fouls": {
                        "status": "conflict",
                        "usable": False,
                        "sources": {
                            "api_football": {"home": 11, "away": 15},
                            "football_data_uk": {"home": 12, "away": 15},
                        },
                        "confidence": 0.0,
                    },
                },
            }
        },
        "affects_1x2": False,
    }


def test_evalua_solo_truth_usable_con_snapshot_prepartido():
    observations, audit = build_observations([_match()], _truth())

    assert len(observations) == 1
    row = observations[0]
    assert row["snapshot_at"] == "2026-08-20T18:00:00+02:00"
    assert row["prediction_origin"] == "dashboard_pre_match_snapshot"
    assert row["affects_1x2"] is False
    assert set(row["stats"]) == {"xg", "shots"}
    assert row["stats"]["shots"]["actual"]["total"] == 23.0
    assert row["stats"]["shots"]["error"]["total"] == -1.0
    assert row["stats"]["xg"]["truth_status"] == "single_source"
    assert row["stats"]["xg"]["truth_sources"] == ["api_football"]
    assert "fouls" not in row["stats"]
    assert audit["evaluated_by_stat"] == {"shots": 1, "xg": 1}


def test_snapshot_postpartido_no_se_usa():
    late = _snapshot("2026-08-20T21:01:00+02:00")
    observations, audit = build_observations([_match(late)], _truth())
    assert observations == []
    assert audit["missing_pre_match_snapshot"] == 1


def test_identidad_exacta_no_invierte_barcelona_espanyol():
    observations, audit = build_observations(
        [_match(home="RCD Espanyol", away="FC Barcelona")],
        _truth(),
    )
    assert observations == []
    assert audit["missing_dashboard"] == 1


def test_conflicto_posterior_invalida_stat_y_no_conserva_valor_viejo():
    first_obs, _ = build_observations([_match()], _truth(xg_usable=True))
    archive, _ = update_archive(
        empty_archive(), first_obs, updated_at="2026-08-21T08:00:00Z"
    )
    assert "xg" in archive["records"]["truth-match-1"]["latest"]["stats"]

    conflict_obs, _ = build_observations(
        [_match()], _truth(xg_usable=False), previous_archive=archive
    )
    archive, summary = update_archive(
        archive, conflict_obs, updated_at="2026-08-22T08:00:00Z"
    )
    latest = archive["records"]["truth-match-1"]["latest"]
    assert summary["added_revisions"] == 1
    assert "xg" not in latest["stats"]
    assert len(archive["records"]["truth-match-1"]["history"]) == 2


def test_correccion_tardia_reutiliza_prediccion_archivada_sin_dashboard():
    first_obs, _ = build_observations([_match()], _truth(shots_home=15))
    archive, _ = update_archive(
        empty_archive(), first_obs, updated_at="2026-08-21T08:00:00Z"
    )

    corrected_obs, audit = build_observations(
        [], _truth(shots_home=16), previous_archive=archive
    )
    assert len(corrected_obs) == 1
    assert corrected_obs[0]["prediction_origin"] == "archived_pre_match_prediction"
    assert corrected_obs[0]["stats"]["shots"]["actual"]["home"] == 16.0
    assert audit["reused_archived_prediction"] == 1

    archive, summary = update_archive(
        archive, corrected_obs, updated_at="2026-08-22T08:00:00Z"
    )
    assert summary["by_stat"]["shots"]["n"] == 1
    assert summary["by_stat"]["shots"]["mae"]["total"] == 2.0
    assert summary["by_stat"]["shots"]["bias_predicted_minus_actual"]["total"] == -2.0


def test_agregado_usa_solo_latest_y_declara_muestra_insuficiente():
    observations, _ = build_observations([_match()], _truth())
    archive, summary = update_archive(
        empty_archive(), observations, updated_at="2026-08-21T08:00:00Z"
    )
    assert archive["schema"] == SCHEMA
    assert summary["evaluated_matches"] == 1
    assert summary["stat_observations"] == 2
    assert summary["by_stat"]["shots"]["sample_stage"] == "insufficient_sample"
    assert summary["promotion_policy"]["automatic_production_promotion"] is False
    assert summary["affects_1x2"] is False


def test_refresh_sin_truth_no_inventa_archivo(tmp_path):
    dashboard = tmp_path / "dashboard.json"
    output = tmp_path / "evaluation.json"
    dashboard.write_text(json.dumps({"matches": [_match()]}), encoding="utf-8")

    report = refresh_truth_evaluation(
        dashboard,
        tmp_path / "missing-truth.json",
        output,
        generated_at="2026-08-21T08:00:00Z",
    )
    assert report["status"] == "truth_unavailable"
    assert output.exists() is False


def test_refresh_persiste_y_repeticion_identica_no_genera_revision(tmp_path):
    dashboard = tmp_path / "dashboard.json"
    truth = tmp_path / "truth.json"
    output = tmp_path / "evaluation.json"
    dashboard.write_text(json.dumps({"matches": [_match()]}), encoding="utf-8")
    truth.write_text(json.dumps(_truth()), encoding="utf-8")

    first = refresh_truth_evaluation(
        dashboard, truth, output, generated_at="2026-08-21T08:00:00Z"
    )
    before = output.read_text(encoding="utf-8")
    second = refresh_truth_evaluation(
        dashboard, truth, output, generated_at="2026-08-22T08:00:00Z"
    )
    after = output.read_text(encoding="utf-8")

    assert first["status"] == "updated"
    assert first["added_revisions"] == 1
    assert second["status"] == "no_change"
    assert second["added_revisions"] == 0
    assert before == after
    saved = json.loads(after)
    assert saved["affects_1x2"] is False
    assert saved["summary"]["by_stat"]["xg"]["source_mix"] == {"api_football": 1}
