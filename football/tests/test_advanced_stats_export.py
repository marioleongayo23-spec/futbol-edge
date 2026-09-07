from datetime import datetime, timezone

import pandas as pd

from futbol_pred.advanced_stats import latest_snapshot_as_of, match_context
from futbol_pred.advanced_stats_export import (
    BACKFILL_AVAILABILITY_POLICY,
    LIVE_AVAILABILITY_POLICY,
    archive_digest,
    archive_manifest,
    build_historical_archive,
    build_live_snapshot,
    conservative_available_at,
    fbref_frames_to_records,
    merge_archives,
    normalise_match_record,
)


def _records():
    return [
        {
            "match_at": "2026-08-20T21:00:00+02:00",
            "team": "FC Barcelona",
            "opponent": "RCD Espanyol",
            "xg_for": 2.0,
            "npxg_for": 1.8,
            "xg_against": 0.7,
            "npxg_against": 0.6,
            "keeper_psxg90": 0.8,
            "keeper_psxg_plus_minus90": 0.2,
            "keeper_minutes": 90,
        },
        {
            "match_at": "2026-08-20T21:00:00+02:00",
            "team": "RCD Espanyol",
            "opponent": "FC Barcelona",
            "xg_for": 0.7,
            "npxg_for": 0.6,
            "xg_against": 2.0,
            "npxg_against": 1.8,
            "keeper_psxg90": 1.9,
            "keeper_psxg_plus_minus90": -0.3,
            "keeper_minutes": 90,
        },
        {
            "match_at": "2026-08-27T19:00:00+02:00",
            "team": "FC Barcelona",
            "opponent": "Valencia",
            "xg_for": 3.0,
            "npxg_for": 2.6,
            "xg_against": 1.1,
            "npxg_against": 1.0,
            "keeper_psxg90": 1.0,
            "keeper_psxg_plus_minus90": 0.4,
            "keeper_minutes": 90,
        },
    ]


def _archive(records=None, *, generated_at="2026-09-07T06:00:00+00:00"):
    return build_historical_archive(
        _records() if records is None else records,
        league="laliga",
        season=2026,
        source="FBref offline test",
        source_version="1.9.1",
        generated_at=generated_at,
    )


def test_backfill_no_hace_disponible_el_partido_el_mismo_dia():
    available = conservative_available_at("2026-08-20T21:00:00+02:00")
    assert available == datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)

    archive = _archive()
    assert latest_snapshot_as_of(
        archive, "laliga", 2026, "2026-08-21T11:59:59+00:00"
    ) is None
    assert latest_snapshot_as_of(
        archive, "laliga", 2026, "2026-08-21T12:00:00+00:00"
    ) is None  # cutoff estricto: available_at debe ser menor
    assert latest_snapshot_as_of(
        archive, "laliga", 2026, "2026-08-21T12:00:01+00:00"
    ) is not None


def test_snapshots_son_acumulativos_sin_mirar_el_partido_futuro():
    archive = _archive()
    assert len(archive["snapshots"]) == 2

    first = archive["snapshots"][0]
    barca_first = first["teams"]["Barcelona"]
    assert barca_first["matches"] == 1
    assert barca_first["xg_for90"] == 2.0
    assert first["availability_policy"] == BACKFILL_AVAILABILITY_POLICY

    second = archive["snapshots"][1]
    barca_second = second["teams"]["Barcelona"]
    assert barca_second["matches"] == 2
    assert barca_second["xg_for90"] == 2.5
    assert barca_second["npxg_for90"] == 2.2


def test_barcelona_y_espanyol_permanecen_separados_en_el_export():
    first = _archive()["snapshots"][0]
    assert set(first["teams"]) == {"Barcelona", "RCD Espanyol"}
    assert first["teams"]["Barcelona"]["xg_for90"] == 2.0
    assert first["teams"]["RCD Espanyol"]["xg_for90"] == 0.7

    context = match_context(first, "FC Barcelona", "RCD Espanyol")
    assert context["home"]["xg_for90"] == 2.0
    assert context["away"]["xg_for90"] == 0.7
    assert context["affects_1x2"] is False


def test_npxg_puede_faltar_sin_invalidar_el_archivo():
    rows = [
        {
            "match_at": "2026-08-20T19:00:00Z",
            "team": "Valencia",
            "xg_for": 1.2,
            "xg_against": 0.9,
        }
    ]
    archive = _archive(rows)
    team = archive["snapshots"][0]["teams"]["Valencia"]
    assert team["xg_for90"] == 1.2
    assert "npxg_for90" not in team


def test_nan_y_fila_sin_senal_se_descartan():
    assert normalise_match_record(
        {"match_at": "2026-08-20", "team": "Valencia", "xg_for": float("nan")}
    ) is None
    assert normalise_match_record(
        {"match_at": "bad-date", "team": "Valencia", "xg_for": 1.0}
    ) is None


def test_merge_deduplica_y_digest_no_depende_del_orden():
    archive = _archive()
    reversed_archive = {
        "schema": archive["schema"],
        "snapshots": list(reversed(archive["snapshots"])),
    }

    merged = merge_archives(archive, reversed_archive)
    assert len(merged["snapshots"]) == len(archive["snapshots"])
    assert archive_digest(archive) == archive_digest(reversed_archive)
    assert archive_digest(merged) == archive_digest(archive)

    manifest = archive_manifest(merged)
    assert manifest["snapshot_count"] == 2
    assert manifest["leagues"] == ["laliga"]
    assert manifest["seasons"] == [2026]
    assert len(manifest["sha256"]) == 64


def test_digest_semantico_ignora_solo_hora_de_reexportacion():
    first = _archive(generated_at="2026-09-07T06:00:00+00:00")
    rerun = _archive(generated_at="2026-09-08T09:30:00+00:00")
    assert first["snapshots"][0]["generated_at"] != rerun["snapshots"][0]["generated_at"]
    assert archive_digest(first) == archive_digest(rerun)

    changed_records = _records()
    changed_records[0] = {**changed_records[0], "xg_for": 2.1}
    changed = _archive(changed_records, generated_at="2026-09-08T09:30:00+00:00")
    assert archive_digest(first) != archive_digest(changed)


def test_keeper_unit_se_agrega_ponderado_por_minutos():
    snapshot = _archive()["snapshots"][1]
    keeper = snapshot["teams"]["Barcelona"]["goalkeepers"][0]

    assert keeper["player"] is None
    assert keeper["minutes"] == 180.0
    assert keeper["psxg90"] == 0.9
    assert keeper["psxg_plus_minus90"] == 0.3


def test_live_snapshot_conserva_hora_real_y_sigue_sin_afectar_1x2():
    live = build_live_snapshot(
        {
            "FC Barcelona": {
                "matches": 3,
                "xg_for90": 2.2,
                "xg_against90": 0.8,
                "goalkeepers": [],
            },
            "RCD Espanyol": {
                "matches": 3,
                "xg_for90": 1.0,
                "xg_against90": 1.6,
                "goalkeepers": [],
            },
        },
        league="laliga",
        season=2026,
        source="live residential capture",
        source_version="1.9.1",
        captured_at="2026-09-07T08:17:31+02:00",
    )
    assert live["available_at"] == "2026-09-07T06:17:31+00:00"
    assert live["availability_policy"] == LIVE_AVAILABILITY_POLICY
    assert live["historical_backfill"] is False
    assert match_context(live, "Barcelona", "RCD Espanyol")["affects_1x2"] is False


def test_fbref_dataframe_adapter_extrae_schedule_npxg_y_psxg():
    schedule = pd.DataFrame(
        {
            "team": ["FC Barcelona", "RCD Espanyol"],
            "date": ["2026-08-20", "2026-08-20"],
            "opponent": ["RCD Espanyol", "FC Barcelona"],
            "xG": [2.0, 0.7],
            "xGA": [0.7, 2.0],
        }
    )
    shooting = pd.DataFrame(
        {
            "team": ["FC Barcelona", "RCD Espanyol"],
            "date": ["2026-08-20", "2026-08-20"],
            "npxG": [1.8, 0.6],
        }
    )
    opponent = pd.DataFrame(
        {
            "team": ["FC Barcelona", "RCD Espanyol"],
            "date": ["2026-08-20", "2026-08-20"],
            "npxG": [0.6, 1.8],
        }
    )
    keeper = pd.DataFrame(
        {
            "team": ["FC Barcelona", "RCD Espanyol"],
            "date": ["2026-08-20", "2026-08-20"],
            "PSxG": [0.8, 1.9],
            "PSxG+/-": [0.2, -0.3],
        }
    )

    records = fbref_frames_to_records(
        schedule,
        shooting_frame=shooting,
        opponent_shooting_frame=opponent,
        keeper_frame=keeper,
    )
    by_team = {
        normalise_match_record(row)["team"]: normalise_match_record(row)
        for row in records
    }

    assert by_team["Barcelona"]["xg_for"] == 2.0
    assert by_team["Barcelona"]["xg_against"] == 0.7
    assert by_team["Barcelona"]["npxg_for"] == 1.8
    assert by_team["Barcelona"]["npxg_against"] == 0.6
    assert by_team["Barcelona"]["keeper_psxg90"] == 0.8
    assert by_team["Barcelona"]["keeper_psxg_plus_minus90"] == 0.2
    assert by_team["RCD Espanyol"]["keeper_psxg_plus_minus90"] == -0.3


def test_dataframe_adapter_tolera_multiindex_de_columnas():
    columns = pd.MultiIndex.from_tuples(
        [
            ("meta", "team"),
            ("meta", "date"),
            ("performance", "xG"),
            ("performance", "xGA"),
        ]
    )
    schedule = pd.DataFrame(
        [["FC Barcelona", "2026-08-20", 2.1, 0.8]],
        columns=columns,
    )
    records = fbref_frames_to_records(schedule)
    row = normalise_match_record(records[0])
    assert row["team"] == "Barcelona"
    assert row["xg_for"] == 2.1
    assert row["xg_against"] == 0.8
