from futbol_pred.data_contract import source_observation
from futbol_pred.source_policy import choose_best_observation


def test_prematch_selection_rejects_future_and_live_data():
    rows = [
        source_observation(
            source="football-data.co.uk",
            source_id="old-real",
            available_at="2026-09-07T08:00:00Z",
            phase="prematch",
            quality="verified",
        ),
        source_observation(
            source="API-Football",
            source_id="live-better-but-illegal",
            available_at="2026-09-07T18:05:00Z",
            phase="live",
            quality="official",
        ),
        source_observation(
            source="API-Football",
            source_id="future-prematch",
            available_at="2026-09-07T17:45:00Z",
            phase="prematch",
            quality="official",
        ),
    ]
    picked = choose_best_observation(
        "team_stats",
        rows,
        prediction_as_of="2026-09-07T17:00:00Z",
        allowed_phases={"prematch"},
    )
    assert picked["source_id"] == "old-real"


def test_domain_specific_priority_prefers_rfef_for_referee():
    rows = [
        source_observation(
            source="API-Football",
            source_id="api-ref",
            available_at="2026-09-07T09:00:00Z",
            quality="official",
        ),
        source_observation(
            source="RFEF",
            source_id="rfef-ref",
            available_at="2026-09-07T09:00:00Z",
            quality="official",
        ),
    ]
    picked = choose_best_observation(
        "referee",
        rows,
        prediction_as_of="2026-09-07T10:00:00Z",
        allowed_phases={"prematch"},
    )
    assert picked["source"] == "RFEF"


def test_quality_beats_source_priority_when_evidence_is_weaker():
    rows = [
        source_observation(
            source="API-Football",
            source_id="estimate",
            available_at="2026-09-07T09:00:00Z",
            quality="estimated",
        ),
        source_observation(
            source="media",
            source_id="verified-media",
            available_at="2026-09-07T09:00:00Z",
            quality="verified",
        ),
    ]
    picked = choose_best_observation(
        "lineup",
        rows,
        prediction_as_of="2026-09-07T10:00:00Z",
        allowed_phases={"prematch"},
    )
    assert picked["source_id"] == "verified-media"


def test_newer_equal_quality_observation_wins_within_same_source():
    rows = [
        source_observation(
            source="The Odds API",
            source_id="snapshot-1",
            available_at="2026-09-07T08:00:00Z",
            quality="observed",
        ),
        source_observation(
            source="The Odds API",
            source_id="snapshot-2",
            available_at="2026-09-07T09:00:00Z",
            quality="observed",
        ),
    ]
    picked = choose_best_observation(
        "odds",
        rows,
        prediction_as_of="2026-09-07T10:00:00Z",
        allowed_phases={"prematch"},
    )
    assert picked["source_id"] == "snapshot-2"
