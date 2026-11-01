import csv
from datetime import datetime, timezone
import json

import pytest

from futbol_pred.feature_store import HistoricalFeatureStore
from futbol_pred.open_data_bridge import import_csv, parse_rows

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
COLUMNS = (
    "record_id", "match_uid", "league", "season", "kickoff", "kickoff_precision",
    "home", "away", "feature", "value_json", "source", "source_url",
    "license", "available_at", "phase", "quality",
)


def row(**overrides):
    result = dict(
        record_id="of-1-v1", match_uid="openfootball:es1:2026:barcelona:betis",
        league="laliga", season="2026", kickoff="2026-10-20T00:00:00Z",
        kickoff_precision="date_only", home="Barcelona", away="Betis",
        feature="result.score", value_json="[2,1]", source="openfootball",
        source_url="https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/es.1.json",
        license="CC0-1.0", available_at="2026-10-21T07:00:00Z",
        phase="postmatch", quality="observed_date_only",
    )
    result.update(overrides)
    return result


def make_csv(path, *rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_reimport_is_idempotent_and_postmatch_never_leaks_into_prematch(tmp_path):
    csv_path = make_csv(tmp_path / "source.csv", row())
    db = tmp_path / "shadow.sqlite"
    assert import_csv(csv_path, db) == {
        "rows_checked": 1, "matches": 1, "observations_added": 1,
        "promotion": "disabled", "source": "openfootball",
    }
    assert import_csv(csv_path, db)["observations_added"] == 0
    store = HistoricalFeatureStore(db)
    assert store.observation_count() == 1
    uid = row()["match_uid"]
    assert store.snapshot_as_of(uid, "2026-10-19T12:00:00Z") == {}
    assert store.snapshot_as_of(uid, "2026-10-22T12:00:00Z") == {}
    available = store.snapshot_as_of(
        uid, "2026-10-22T12:00:00Z", phases=("postmatch",),
    )
    assert available[("result.score", "match")]["value"] == [2, 1]
    assert available[("result.score", "match")]["quality"] == "observed_date_only"


@pytest.mark.parametrize("override", [
    {"source": "football-data.co.uk"},
    {"source": "openfootball", "license": "unknown"},
    {"source_url": "https://private-site.example/paywall"},
    {"phase": "prematch"},
    {"feature": "odds.1x2"},
    {"value_json": "[1, -2]"},
    {"value_json": "[1.1, 2]"},
    {"available_at": "2026-11-03T00:00:00Z"},
    {"available_at": "2026-10-21T07:00:00"},
    {"kickoff_precision": "minute", "available_at": "2026-10-19T07:00:00Z"},
])
def test_rejects_unlicensed_fake_or_unverifiable_rows(tmp_path, override):
    path = make_csv(tmp_path / "bridge.csv", row(**override))
    with pytest.raises(ValueError):
        parse_rows(path, now=NOW)


def test_invalid_batch_does_not_write_partial_rows(tmp_path):
    path = make_csv(tmp_path / "bridge.csv", row(), row(record_id="bad", source="premium-via-sheets"))
    db = tmp_path / "shadow.sqlite"
    with pytest.raises(ValueError):
        import_csv(path, db)
    assert not db.exists()


def test_distinct_time_observations_and_source_revisions_are_immutable(tmp_path):
    uid = row()["match_uid"]
    path = make_csv(tmp_path / "bridge.csv",
                    row(),
                    row(record_id="of-1-v2", available_at="2026-10-22T07:00:00Z",
                        value_json="[3,1]"))
    db = tmp_path / "shadow.sqlite"
    assert import_csv(path, db)["observations_added"] == 2
    store = HistoricalFeatureStore(db)
    prior = store.snapshot_as_of(uid, "2026-10-21T12:00:00Z", phases=("postmatch",))
    assert prior[("result.score", "match")]["value"] == [2, 1]
    after = store.snapshot_as_of(uid, "2026-10-22T12:00:00Z", phases=("postmatch",))
    assert after[("result.score", "match")]["value"] == [3, 1]
