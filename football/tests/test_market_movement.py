from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from futbol_pred.market_movement import (
    POLICY_SCHEMA,
    append_market_snapshot,
    apply_movement_policy,
    build_market_snapshot,
    learn_market_movement_challenger,
    movement_summary,
)
from futbol_pred.prediction_snapshots import apply_prediction_snapshots

MADRID = ZoneInfo("Europe/Madrid")


def _snapshot(kickoff, captured, fair, *, source_updated=None):
    odds = {"1": 2.0, "X": 3.4, "2": 4.2}
    return build_market_snapshot(
        kickoff=kickoff,
        captured_at=captured,
        odds_1x2=odds,
        fair_1x2=fair,
        provider="The Odds API",
        source_updated_at=source_updated or captured,
    )


def test_snapshot_posterior_al_kickoff_se_rechaza():
    kickoff = datetime(2026, 9, 7, 21, tzinfo=MADRID)
    assert _snapshot(
        kickoff,
        kickoff + timedelta(minutes=1),
        {"1": 0.5, "X": 0.3, "2": 0.2},
    ) is None


def test_history_comprime_ticks_identicos_y_resume_movimiento_no_vig():
    kickoff = datetime(2026, 9, 7, 21, tzinfo=MADRID)
    match = {}
    first = _snapshot(
        kickoff,
        kickoff - timedelta(hours=4),
        {"1": 0.45, "X": 0.30, "2": 0.25},
        source_updated="2026-09-07T16:55:00+02:00",
    )
    duplicate = _snapshot(
        kickoff,
        kickoff - timedelta(hours=3, minutes=50),
        {"1": 0.45, "X": 0.30, "2": 0.25},
        source_updated="2026-09-07T16:55:00+02:00",
    )
    moved = _snapshot(
        kickoff,
        kickoff - timedelta(hours=2),
        {"1": 0.50, "X": 0.28, "2": 0.22},
    )

    assert append_market_snapshot(match, first) is True
    assert append_market_snapshot(match, duplicate) is False
    assert append_market_snapshot(match, moved) is True
    assert len(match["market_history"]) == 2

    summary = movement_summary(match["market_history"], kickoff=kickoff)
    assert summary["n_snapshots"] == 2
    assert summary["delta_pp"] == {"1": 5.0, "X": -2.0, "2": -3.0}
    assert summary["provider"] == "The Odds API"


def test_challenger_no_usa_closing_odds_como_backfill():
    kickoff = datetime(2026, 8, 20, 21, tzinfo=MADRID)
    match = {
        "kickoff": kickoff.isoformat(),
        "finished": True,
        "result": [1, 0],
        "closing_odds": {"1x2": {"1": 1.8, "X": 3.7, "2": 4.5}},
        "prediction_history": [{
            "generated_at": (kickoff - timedelta(hours=2)).isoformat(),
            "window": "T-3h",
            "probs": [45, 30, 25],
        }],
    }

    policy = learn_market_movement_challenger([match], min_sample=1)
    assert policy["accepted"] is False
    assert policy["status"] == "blocked_insufficient_live_snapshots"
    assert policy["n"] == 0
    assert policy["source_policy"] == "live_prematch_snapshots_only_no_closing_backfill"


def test_policy_aceptada_solo_si_mejora_misma_cola_temporal():
    matches = []
    start = datetime(2026, 1, 1, 21, tzinfo=MADRID)
    for index in range(60):
        kickoff = start + timedelta(days=index)
        open_snapshot = _snapshot(
            kickoff,
            kickoff - timedelta(hours=12),
            {"1": 0.34, "X": 0.33, "2": 0.33},
        )
        moved_snapshot = _snapshot(
            kickoff,
            kickoff - timedelta(hours=3),
            {"1": 0.52, "X": 0.24, "2": 0.24},
        )
        matches.append({
            "kickoff": kickoff.isoformat(),
            "finished": True,
            "result": [1, 0],
            "market_history": [open_snapshot, moved_snapshot],
            "prediction_history": [{
                "generated_at": (kickoff - timedelta(hours=2)).isoformat(),
                "window": "T-3h",
                "probs": [34, 33, 33],
            }],
        })

    policy = learn_market_movement_challenger(matches)
    assert policy["accepted"] is True
    assert policy["status"] == "accepted"
    assert policy["n_validation"] >= 20
    assert policy["validation"]["candidate"]["log_loss"] < policy["validation"]["baseline"]["log_loss"]
    assert policy["validation"]["candidate"]["rps"] < policy["validation"]["baseline"]["rps"]
    assert policy["production"]["beta"] > 0


def test_policy_aplica_delta_y_mantiene_probabilidad_normalizada():
    movement = {
        "delta_pp": {"1": 5.0, "X": -2.0, "2": -3.0},
    }
    policy = {
        "schema": POLICY_SCHEMA,
        "accepted": True,
        "production": {"beta": 2.0},
    }
    adjusted = apply_movement_policy([40, 32, 28], movement, policy)
    assert adjusted["1"] > 0.40
    assert abs(sum(adjusted.values()) - 1.0) < 1e-12


def test_rebuild_preserva_market_history_y_snapshot_archiva_ajuste():
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    history = [
        _snapshot(kickoff, kickoff - timedelta(hours=12), {"1": 0.40, "X": 0.32, "2": 0.28}),
        _snapshot(kickoff, kickoff - timedelta(hours=4), {"1": 0.44, "X": 0.30, "2": 0.26}),
    ]
    old = {
        "id": "m-market",
        "date": "2026-08-24",
        "kickoff": kickoff.isoformat(),
        "league": "LaLiga",
        "home": "A",
        "away": "B",
        "finished": False,
        "probs": [48, 30, 22],
        "model_meta": {"version": "edge-2.1"},
        "market_history": history,
        "market_movement": movement_summary(history, kickoff=kickoff),
        "market_movement_adjustment": {
            "before": [47, 31, 22],
            "after": [48, 30, 22],
            "beta": 1.0,
        },
    }
    apply_prediction_snapshots([old], [], datetime(2026, 8, 23, 15, tzinfo=MADRID))

    rebuilt = {
        "id": "m-market",
        "date": "2026-08-24",
        "kickoff": kickoff.isoformat(),
        "league": "LaLiga",
        "home": "A",
        "away": "B",
        "finished": False,
        "probs": [70, 20, 10],
        "model_meta": {"version": "edge-2.1"},
    }
    apply_prediction_snapshots([rebuilt], [old], datetime(2026, 8, 24, 8, tzinfo=MADRID))

    assert len(rebuilt["market_history"]) == 2
    assert rebuilt["market_history"][0]["captured_at"] == history[0]["captured_at"]
    assert rebuilt["prediction_snapshot"]["market_movement_adjustment"]["before"] == [47, 31, 22]
