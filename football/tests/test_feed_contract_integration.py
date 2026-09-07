from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from futbol_pred.feed_quality import write_feed_safely


BASE = datetime(2026, 9, 10, 19, 0, tzinfo=timezone.utc)


def _match(index: int, *, source: str = "api-football", home: str = "Barcelona", away: str = "Espanol") -> dict:
    kickoff = BASE + timedelta(days=index)
    return {
        "id": f"{source}-{1000 + index}",
        "date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "home": home,
        "away": away,
        "league": "LaLiga",
        "status": "SCHEDULED",
        "finished": False,
        "source": source,
        "engine": "calendar-only",
        "updatedAt": "2026-09-07T04:00:00+00:00",
    }


def _payload(matches: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "season": 2026,
        "generated_at": "2026-09-07T04:00:00+00:00",
        "matches": matches,
        "counts": {
            "total": len(matches),
            "jugados": 0,
            "proximos": len(matches),
            "con_prediccion": 0,
        },
    }


def test_write_feed_enriches_contract_and_dedupes_cross_provider(tmp_path):
    matches = [_match(i) for i in range(20)]
    duplicate = _match(
        0,
        source="football-data.org",
        home="FC Barcelona",
        away="RCD Espanyol de Barcelona",
    )
    duplicate["id"] = "football-data.org-abc-0"
    duplicate["venue"] = "Estadi Olímpic"
    matches.append(duplicate)
    payload = _payload(matches)

    ok, report = write_feed_safely(tmp_path / "dashboard.json", payload, previous=None)

    assert ok is True
    assert report["valid"] is True
    assert report["metrics"]["deduped_match_uids"] == 1
    assert len(payload["matches"]) == 20
    assert payload["counts"]["total"] == 20

    first = next(match for match in payload["matches"] if match["date"] == BASE.date().isoformat())
    assert first["match_uid"].endswith(":barcelona:espanol")
    assert first["id"] in {"api-football-1000", "football-data.org-abc-0"}
    assert set(first["source_refs"]) == {"api-football", "football-data.org"}
    assert first["provenance"]["fixture"]["phase"] == "prematch"
    assert first["provenance"]["fixture"]["available_at"] == "2026-09-07T04:00:00+00:00"


def test_last_known_good_matches_same_fixture_after_provider_change(tmp_path):
    previous_matches = [_match(i) for i in range(20)]
    previous_matches[0]["h2h"] = [{"score": "2-1"}]
    previous = _payload(previous_matches)

    candidate_matches = [deepcopy(match) for match in previous_matches]
    candidate_matches[0] = _match(
        0,
        source="football-data.org",
        home="FC Barcelona",
        away="RCD Espanyol de Barcelona",
    )
    candidate_matches[0]["id"] = "football-data.org-replacement"
    candidate = _payload(candidate_matches)

    ok, report = write_feed_safely(tmp_path / "dashboard.json", candidate, previous=previous)

    assert ok is True
    assert report["valid"] is True
    assert candidate["matches"][0]["h2h"] == [{"score": "2-1"}]
    assert candidate["matches"][0]["match_uid"] == previous["matches"][0]["match_uid"]


def test_finished_match_gets_postmatch_result_provenance(tmp_path):
    matches = [_match(i) for i in range(20)]
    matches[0]["finished"] = True
    matches[0]["status"] = "FINISHED"
    matches[0]["result"] = [3, 1]
    payload = _payload(matches)
    payload["counts"]["jugados"] = 1
    payload["counts"]["proximos"] = 19

    ok, report = write_feed_safely(tmp_path / "dashboard.json", payload, previous=None)

    assert ok is True
    assert report["valid"] is True
    provenance = payload["matches"][0]["provenance"]
    assert provenance["fixture"]["phase"] == "postmatch"
    assert provenance["result"]["phase"] == "postmatch"


def test_live_match_is_never_labeled_prematch(tmp_path):
    matches = [_match(i) for i in range(20)]
    matches[0]["status"] = "IN_PLAY"
    payload = _payload(matches)

    ok, report = write_feed_safely(tmp_path / "dashboard.json", payload, previous=None)

    assert ok is True
    assert report["valid"] is True
    assert payload["matches"][0]["provenance"]["fixture"]["phase"] == "live"
