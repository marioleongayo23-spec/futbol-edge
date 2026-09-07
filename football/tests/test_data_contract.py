from datetime import datetime, timezone

import pytest

from futbol_pred.data_contract import (
    canonical_match_uid,
    is_available_as_of,
    source_observation,
)


def test_same_match_same_uid_across_provider_aliases_and_timezones():
    from_api = canonical_match_uid(
        "laliga",
        2026,
        "FC Barcelona",
        "RCD Espanyol de Barcelona",
        "2026-10-18T21:00:00+02:00",
    )
    from_csv = canonical_match_uid(
        "laliga",
        2026,
        "Barcelona",
        "Espanol",
        "2026-10-18T19:00:00Z",
    )
    assert from_api == from_csv
    assert from_api.endswith(":barcelona:espanol")


def test_barcelona_and_espanyol_never_collapse_to_same_team_identity():
    uid = canonical_match_uid(
        "laliga",
        2026,
        "Barcelona",
        "Espanyol",
        datetime(2026, 10, 18, 21, 0),
    )
    assert ":barcelona:espanol" in uid

    with pytest.raises(ValueError):
        canonical_match_uid(
            "laliga",
            2026,
            "FC Barcelona",
            "Barcelona FC",
            datetime(2026, 10, 18, 21, 0),
        )


def test_provider_ids_do_not_participate_in_match_uid():
    uid = canonical_match_uid(
        "laliga", 2026, "Real Madrid CF", "Real Betis", "2026-09-20T18:30:00+02:00"
    )
    api = source_observation(
        source="API-Football",
        source_id=123456,
        available_at="2026-09-20T12:00:00+02:00",
        quality="official",
    )
    csv = source_observation(
        source="football-data.co.uk",
        source_id="SP1-row-42",
        available_at="2026-09-20T10:00:00Z",
        quality="verified",
    )
    assert uid == "laliga:2026:20260920:real-madrid:betis"
    assert api["source_id"] != csv["source_id"]


def test_available_at_is_normalized_and_blocks_future_information():
    observation = source_observation(
        source="API-Football",
        source_id=77,
        available_at="2026-09-07T10:30:00+02:00",
        observed_at="2026-09-07T10:31:00+02:00",
        phase="prematch",
        quality="official",
    )
    assert observation["available_at"] == "2026-09-07T08:30:00+00:00"
    assert not is_available_as_of(observation, "2026-09-07T08:29:59Z")
    assert is_available_as_of(observation, "2026-09-07T08:30:00Z")


def test_live_or_postmatch_phase_is_explicit():
    live = source_observation(
        source="API-Football",
        source_id=99,
        available_at=datetime(2026, 9, 7, 20, 5, tzinfo=timezone.utc),
        phase="live",
    )
    post = source_observation(
        source="football-data.co.uk",
        source_id="SP1-99",
        available_at=datetime(2026, 9, 7, 22, 0, tzinfo=timezone.utc),
        phase="postmatch",
    )
    assert live["phase"] == "live"
    assert post["phase"] == "postmatch"


def test_invalid_contract_values_fail_closed():
    with pytest.raises(ValueError):
        source_observation(
            source="API-Football",
            source_id=1,
            available_at="2026-09-07T08:00:00Z",
            phase="future",
        )
    with pytest.raises(ValueError):
        source_observation(
            source="API-Football",
            source_id=1,
            available_at="2026-09-07T08:00:00Z",
            quality="magic",
        )
