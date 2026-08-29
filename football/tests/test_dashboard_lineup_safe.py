from datetime import datetime, timezone

import futbol_pred.dashboard_lineup_safe as safe


class _Online:
    offline = False


def test_build_candidate_applies_lineup_baseline_before_publication(monkeypatch):
    now = datetime(2026, 8, 29, 6, 0, tzinfo=timezone.utc)
    candidate = {"matches": [{"id": "m1"}], "generated_at": now.isoformat()}
    previous = {
        "matches": [{"id": "old"}],
        "source_health": {"api_football": {"daily_remaining": 42}},
        "feed_quality": {"valid": True},
    }
    seen = {}

    monkeypatch.setattr(safe, "load_feed", lambda _path: previous)
    monkeypatch.setattr(safe.dashboard, "build_dashboard", lambda now=None: candidate)

    def fake_baseline(payload, now=None):
        seen["source_health"] = payload.get("source_health")
        payload["matches"][0]["alineacion"] = {"source_quality": "official_history_baseline"}
        return True, {"baseline": 1}

    monkeypatch.setattr(safe, "refresh_lineup_baseline", fake_baseline)

    payload, stats = safe.build_candidate(now=now)

    assert payload["matches"][0]["alineacion"]["source_quality"] == "official_history_baseline"
    assert seen["source_health"]["api_football"]["daily_remaining"] == 42
    assert stats["baseline"] == 1


def test_quality_rejection_keeps_valid_previous_without_failed_run(monkeypatch):
    previous = {
        "matches": [{"id": "old"}],
        "feed_quality": {"valid": True},
    }
    candidate = {"matches": [{"id": "new"}]}

    monkeypatch.setattr(safe.dashboard, "FootballDataClient", lambda: _Online())
    monkeypatch.setattr(safe.dashboard, "ApiFootballClient", lambda: _Online())
    monkeypatch.setattr(safe, "load_feed", lambda _path: previous)
    monkeypatch.setattr(safe, "build_candidate", lambda: (candidate, {"baseline": 0}))
    monkeypatch.setattr(
        safe,
        "write_feed_safely",
        lambda *_a, **_k: (False, {"issues": ["once_vacio_proximo:m1"], "metrics": {}}),
    )

    assert safe.main() == 0


def test_quality_rejection_still_fails_without_last_known_good(monkeypatch):
    candidate = {"matches": [{"id": "new"}]}

    monkeypatch.setattr(safe.dashboard, "FootballDataClient", lambda: _Online())
    monkeypatch.setattr(safe.dashboard, "ApiFootballClient", lambda: _Online())
    monkeypatch.setattr(safe, "load_feed", lambda _path: None)
    monkeypatch.setattr(safe, "build_candidate", lambda: (candidate, {"baseline": 0}))
    monkeypatch.setattr(
        safe,
        "write_feed_safely",
        lambda *_a, **_k: (False, {"issues": ["once_vacio_proximo:m1"], "metrics": {}}),
    )

    assert safe.main() == 4
