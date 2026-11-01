import csv
from datetime import datetime, timezone

import pytest

from futbol_pred.openfootball_archive import collect_rows, source_urls, update_csv
from futbol_pred.open_data_bridge import parse_rows

STAMP = "2026-10-28T12:45:00+00:00"


def sample_score(home=2, away=0):
    return {"date": "2026-10-27", "team1": "Rayo", "team2": "Celta",
            "score": {"ft": [home, away]}}


def fake_fetch(url):
    return {"matches": [
        sample_score(),
        {"date": "2026-10-28", "team1": "Betis", "team2": "Mallorca",
         "score": None},
    ]}


def test_canonical_archive_rows_match_google_sheet_contract(tmp_path):
    rows = collect_rows(2026, seasons_back=0, observed_at=STAMP, fetch=fake_fetch)
    assert len(rows) == 2
    assert rows[0]["match_uid"] == "openfootball:es1:2026:rayo:celta"
    assert rows[0]["kickoff_precision"] == "date_only"
    assert rows[0]["phase"] == "postmatch"
    assert rows[0]["value_json"] == "[2,0]"
    assert rows[0]["license"] == "CC0-1.0"
    path = tmp_path / "obs.csv"
    assert update_csv(path, rows)["new"] == 2
    assert len(parse_rows(path)) == 2
    text = path.read_bytes()
    assert update_csv(path, rows)["new"] == 0
    assert path.read_bytes() == text


def test_observed_revision_appends_without_replacing_first_observation(tmp_path):
    p = tmp_path / "archive.csv"
    first = collect_rows(2026, seasons_back=0, observed_at=STAMP,
                         fetch=fake_fetch)
    changed = collect_rows(
        2026, seasons_back=0, observed_at="2026-10-29T12:45:00+00:00",
        fetch=lambda url: {"matches": [sample_score(home=3, away=1)]},
    )
    assert update_csv(p, first)["new"] == 2
    assert update_csv(p, changed)["new"] == 2
    with p.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["available_at"] == STAMP
    assert rows[0]["value_json"] == "[2,0]"
    assert rows[2]["value_json"] == "[3,1]"
    assert len({r["record_id"] for r in rows}) == 4


def test_openfootball_archive_does_not_store_unsupported_future_claims():
    rows = collect_rows(2026, seasons_back=0, observed_at=STAMP, fetch=lambda url: {
        "matches": [
            {"date": "2026-10-27", "team1": "Rayo", "team2": "Celta",
             "score": [1, 2]},
            {"date": "2026-10-31", "team1": "A", "team2": "B", "score": [0]},
            {"date": "2026-10-29", "team1": "A", "team2": "B", "score": ["1", 0]},
            {"date": "2026-10-99", "team1": "A", "team2": "B", "score": [2, 1]},
        ],
    })
    assert len(rows) == 2
    assert all(row["feature"] == "result.score" for row in rows)


def test_archive_rejects_unlicensed_existing_csv_before_modifying(tmp_path):
    path = tmp_path / "obs.csv"
    rows = collect_rows(2026, seasons_back=0, observed_at=STAMP, fetch=fake_fetch)
    update_csv(path, rows)
    tampered = path.read_text().replace("CC0-1.0", "commercial-premium")
    path.write_text(tampered)
    with pytest.raises(ValueError):
        update_csv(path, rows)
    assert path.read_text() == tampered


def test_source_allowlist_and_season_limits():
    assert len(source_urls(2026, 1)) == 4
    with pytest.raises(ValueError):
        source_urls(2026, 20)
    assert all(url.startswith(
        "https://raw.githubusercontent.com/openfootball/football.json/master"
    ) for url, *_ in source_urls(2026, 0))
