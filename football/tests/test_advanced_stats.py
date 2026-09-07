from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from futbol_pred.advanced_stats import (
    ARCHIVE_SCHEMA,
    SCHEMA,
    attach_advanced_context,
    latest_snapshot_as_of,
    match_context,
    normalise_snapshot,
    shrink_rate,
)

MADRID = ZoneInfo("Europe/Madrid")


def _snapshot(available_at: str, *, source="FBref offline snapshot"):
    return {
        "schema": SCHEMA,
        "source": source,
        "source_version": "soccerdata-1.9.1",
        "generated_at": available_at,
        "available_at": available_at,
        "league": "laliga",
        "season": 2026,
        "league_keeper_psxg_plus_minus90": 0.0,
        "teams": {
            "FC Barcelona": {
                "matches": 6,
                "xg_for90": 2.25,
                "npxg_for90": 2.05,
                "xg_against90": 0.82,
                "npxg_against90": 0.72,
                "goalkeepers": [{
                    "player": "Portero Barça",
                    "minutes": 540,
                    "psxg90": 0.92,
                    "psxg_plus_minus90": 0.30,
                }],
            },
            "RCD Espanyol": {
                "matches": 6,
                "xg_for90": 1.02,
                "npxg_for90": 0.91,
                "xg_against90": 1.65,
                "npxg_against90": 1.51,
                "goalkeepers": [{
                    "player": "Portero Espanyol",
                    "minutes": 90,
                    "psxg90": 1.44,
                    "psxg_plus_minus90": -0.60,
                }],
            },
        },
    }


def test_latest_snapshot_as_of_rechaza_snapshot_del_futuro():
    cutoff = datetime(2026, 9, 7, 18, tzinfo=MADRID)
    old = _snapshot((cutoff - timedelta(hours=2)).isoformat())
    future = _snapshot((cutoff + timedelta(minutes=1)).isoformat(), source="future")
    archive = {"schema": ARCHIVE_SCHEMA, "snapshots": [old, future]}

    selected = latest_snapshot_as_of(archive, "laliga", 2026, cutoff)

    assert selected["source"] == "FBref offline snapshot"
    assert selected["available_at"] == old["available_at"]


def test_cutoff_es_estricto_available_at_igual_no_entra():
    cutoff = datetime(2026, 9, 7, 18, tzinfo=MADRID)
    archive = {"schema": ARCHIVE_SCHEMA, "snapshots": [_snapshot(cutoff.isoformat())]}
    assert latest_snapshot_as_of(archive, "laliga", 2026, cutoff) is None


def test_barcelona_y_espanyol_no_comparten_contexto():
    snapshot = normalise_snapshot(_snapshot("2026-09-07T10:00:00+02:00"))
    context = match_context(snapshot, "FC Barcelona", "RCD Espanyol")

    assert context["home"]["xg_for90"] == 2.25
    assert context["away"]["xg_for90"] == 1.02
    assert context["home"]["goalkeeper"]["player"] == "Portero Barça"
    assert context["away"]["goalkeeper"]["player"] == "Portero Espanyol"
    assert context["affects_1x2"] is False


def test_portero_con_poca_muestra_se_encoge_mas_hacia_media():
    full = shrink_rate(0.60, 1800, league_rate=0.0)
    tiny = shrink_rate(0.60, 90, league_rate=0.0)

    assert full is not None and tiny is not None
    assert 0 < tiny < full < 0.60


def test_attach_context_no_toca_probs_y_usa_cutoff_partido():
    now = datetime(2026, 9, 7, 12, tzinfo=MADRID)
    kickoff = datetime(2026, 9, 7, 21, tzinfo=MADRID)
    archive = {
        "schema": ARCHIVE_SCHEMA,
        "snapshots": [
            _snapshot("2026-09-07T10:00:00+02:00"),
            _snapshot("2026-09-07T20:00:00+02:00", source="not-yet-available"),
        ],
    }
    match = {
        "league": "LaLiga",
        "home": "FC Barcelona",
        "away": "RCD Espanyol",
        "kickoff": kickoff.isoformat(),
        "probs": [62, 22, 16],
    }

    attached = attach_advanced_context([match], archive, season=2026, now=now)

    assert attached == 1
    assert match["probs"] == [62, 22, 16]
    assert match["advanced_stats"]["source"] == "FBref offline snapshot"
    assert match["advanced_stats"]["status"] == "candidate_context_only"


def test_snapshot_con_alias_duplicado_se_rechaza():
    raw = _snapshot("2026-09-07T10:00:00+02:00")
    raw["teams"]["Barcelona"] = raw["teams"]["FC Barcelona"].copy()
    with pytest.raises(ValueError, match="team_duplicate"):
        normalise_snapshot(raw)
