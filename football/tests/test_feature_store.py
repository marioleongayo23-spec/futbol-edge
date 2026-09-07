from __future__ import annotations

from datetime import datetime, timezone

from futbol_pred.feature_store import HistoricalFeatureStore


UID = "laliga:2026:20260910:barcelona:espanol"


def _store(tmp_path):
    store = HistoricalFeatureStore(tmp_path / "features.sqlite")
    store.upsert_match(
        match_uid=UID,
        league="LaLiga",
        season=2026,
        kickoff="2026-09-10T19:00:00+00:00",
        home_team="Barcelona",
        away_team="Espanol",
        updated_at="2026-09-07T04:00:00+00:00",
    )
    return store


def test_snapshot_as_of_excludes_future_observation(tmp_path):
    store = _store(tmp_path)
    store.append_observation(
        match_uid=UID,
        feature="odds.1x2.home",
        value=1.82,
        source="The Odds API",
        available_at="2026-09-09T10:00:00+00:00",
        quality="verified",
    )
    store.append_observation(
        match_uid=UID,
        feature="odds.1x2.home",
        value=1.70,
        source="The Odds API",
        available_at="2026-09-10T17:00:00+00:00",
        quality="verified",
    )

    snap = store.snapshot_as_of(UID, "2026-09-10T12:00:00+00:00")

    assert snap[("odds.1x2.home", "match")]["value"] == 1.82
    assert snap[("odds.1x2.home", "match")]["available_at"] == "2026-09-09T10:00:00+00:00"


def test_default_snapshot_never_uses_live_or_postmatch(tmp_path):
    store = _store(tmp_path)
    store.append_observation(
        match_uid=UID,
        feature="lineup.strength_delta",
        value=0.11,
        source="API-Football",
        available_at="2026-09-10T18:00:00+00:00",
        phase="prematch",
        quality="verified",
    )
    store.append_observation(
        match_uid=UID,
        feature="stats.shots",
        entity="home",
        value=7,
        source="API-Football",
        available_at="2026-09-10T19:20:00+00:00",
        phase="live",
        quality="official",
    )
    store.append_observation(
        match_uid=UID,
        feature="result.score",
        value=[2, 1],
        source="API-Football",
        available_at="2026-09-10T21:00:00+00:00",
        phase="postmatch",
        quality="official",
    )

    snap = store.snapshot_as_of(UID, "2026-09-11T12:00:00+00:00")

    assert ("lineup.strength_delta", "match") in snap
    assert ("stats.shots", "home") not in snap
    assert ("result.score", "match") not in snap


def test_latest_causally_available_observation_wins(tmp_path):
    store = _store(tmp_path)
    for stamp, value in (
        ("2026-09-09T09:00:00+00:00", 0.52),
        ("2026-09-09T18:00:00+00:00", 0.55),
        ("2026-09-10T08:00:00+00:00", 0.58),
    ):
        store.append_observation(
            match_uid=UID,
            feature="market.home_prob",
            value=value,
            source="The Odds API",
            available_at=stamp,
            quality="verified",
        )

    snap = store.snapshot_as_of(UID, "2026-09-10T09:00:00+00:00")

    assert snap[("market.home_prob", "match")]["value"] == 0.58


def test_archive_feed_persists_result_and_final_stats(tmp_path):
    store = HistoricalFeatureStore(tmp_path / "features.sqlite")
    payload = {
        "season": 2026,
        "generated_at": "2026-09-10T21:15:00+00:00",
        "matches": [
            {
                "id": "api-football-123",
                "date": "2026-09-10",
                "kickoff": "2026-09-10T19:00:00+00:00",
                "home": "FC Barcelona",
                "away": "RCD Espanyol de Barcelona",
                "league": "LaLiga",
                "status": "FINISHED",
                "finished": True,
                "source": "api-football",
                "updatedAt": "2026-09-10T21:10:00+00:00",
                "result": [2, 1],
                "statsReal": {
                    "shots": {"home": 15, "away": 8, "total": 23},
                    "sot": {"home": 6, "away": 3, "total": 9},
                },
                "statsRealSource": "API-Football · final",
                "statsRealUpdatedAt": "2026-09-10T21:05:00+00:00",
            }
        ],
    }

    counts = store.archive_feed(payload)
    match_uid = payload["matches"][0]["match_uid"]
    post = store.snapshot_as_of(
        match_uid,
        "2026-09-11T00:00:00+00:00",
        phases=("postmatch",),
    )

    assert counts == {"matches": 1, "observations": 7}
    assert post[("result.score", "match")]["value"] == [2, 1]
    assert post[("stats.shots", "home")]["value"] == 15
    assert post[("stats.shots", "away")]["value"] == 8
    assert post[("stats.sot", "total")]["value"] == 9
