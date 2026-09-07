from copy import deepcopy

import pytest

from futbol_pred.advanced_stats_export import archive_digest, build_historical_archive
from futbol_pred.advanced_stats_intake import empty_archive, load_archive_strict
from futbol_pred.residential_capture import (
    CaptureError,
    atomic_write_archive,
    build_capture_report,
    combine_capture_archives,
    parse_leagues,
    validate_capture_archive,
)


def _archive(league: str, *, season: int = 2026, xg: float = 1.6, day: int = 20):
    records = [
        {
            "match_at": f"2026-08-{day:02d}T19:00:00Z",
            "team": "FC Barcelona" if league == "laliga" else "Albacete",
            "opponent": "RCD Espanyol" if league == "laliga" else "Burgos",
            "xg_for": xg,
            "npxg_for": max(0.0, xg - 0.1),
            "xg_against": 0.8,
            "npxg_against": 0.7,
            "keeper_psxg90": 0.9,
            "keeper_psxg_plus_minus90": 0.1,
            "keeper_minutes": 90,
        },
        {
            "match_at": f"2026-08-{day:02d}T19:00:00Z",
            "team": "RCD Espanyol" if league == "laliga" else "Burgos",
            "opponent": "FC Barcelona" if league == "laliga" else "Albacete",
            "xg_for": 0.8,
            "npxg_for": 0.7,
            "xg_against": xg,
            "npxg_against": max(0.0, xg - 0.1),
            "keeper_psxg90": 1.5,
            "keeper_psxg_plus_minus90": -0.1,
            "keeper_minutes": 90,
        },
    ]
    return build_historical_archive(
        records,
        league=league,
        season=season,
        source="synthetic-residential-test",
        source_version="1",
        generated_at="2026-09-01T12:00:00Z",
    )


def test_parse_leagues_default_dedup_y_rechazo():
    assert parse_leagues(None) == ("laliga", "segunda")
    assert parse_leagues("laliga,segunda,laliga") == ("laliga", "segunda")
    with pytest.raises(CaptureError, match="unsupported_leagues"):
        parse_leagues("laliga,premier")
    with pytest.raises(CaptureError, match="no_leagues_requested"):
        parse_leagues("")


def test_validate_capture_exige_scope_exacto():
    row = validate_capture_archive(_archive("laliga"), league="laliga", season=2026)
    assert row["snapshots"] == 1
    assert row["teams"] == 2
    with pytest.raises(CaptureError, match="capture_scope_mismatch"):
        validate_capture_archive(_archive("laliga"), league="segunda", season=2026)


def test_dos_ligas_se_fusionan_solo_tras_validar_ambas():
    existing = empty_archive()
    candidate, summary = combine_capture_archives(
        existing,
        {"laliga": _archive("laliga"), "segunda": _archive("segunda")},
        leagues=("laliga", "segunda"),
        season=2026,
    )
    assert summary["status"] == "ready"
    assert summary["added"] == 2
    assert summary["manifest"]["snapshot_count"] == 2
    assert {row["league"] for row in candidate["snapshots"]} == {"laliga", "segunda"}
    assert summary["affects_1x2"] is False


def test_falta_segunda_no_devuelve_candidato_parcial_ni_muta_existing():
    existing = empty_archive()
    before = deepcopy(existing)
    with pytest.raises(CaptureError, match="missing_capture:segunda"):
        combine_capture_archives(
            existing,
            {"laliga": _archive("laliga")},
            leagues=("laliga", "segunda"),
            season=2026,
        )
    assert existing == before


def test_scope_incorrecto_en_segunda_no_muta_existing():
    existing = empty_archive()
    before_digest = archive_digest(existing)
    with pytest.raises(CaptureError, match="capture_scope_mismatch"):
        combine_capture_archives(
            existing,
            {"laliga": _archive("laliga"), "segunda": _archive("laliga")},
            leagues=("laliga", "segunda"),
            season=2026,
        )
    assert archive_digest(existing) == before_digest


def test_conflicto_semantico_de_una_liga_aborta_toda_la_transaccion():
    existing, _ = combine_capture_archives(
        empty_archive(),
        {"laliga": _archive("laliga", xg=1.6)},
        leagues=("laliga",),
        season=2026,
    )
    before = archive_digest(existing)
    with pytest.raises(CaptureError, match="intake_rejected:laliga:semantic_key_conflict"):
        combine_capture_archives(
            existing,
            {"laliga": _archive("laliga", xg=2.2)},
            leagues=("laliga",),
            season=2026,
        )
    assert archive_digest(existing) == before


def test_repeticion_identica_es_no_change():
    existing, _ = combine_capture_archives(
        empty_archive(),
        {"laliga": _archive("laliga")},
        leagues=("laliga",),
        season=2026,
    )
    candidate, summary = combine_capture_archives(
        existing,
        {"laliga": _archive("laliga")},
        leagues=("laliga",),
        season=2026,
    )
    assert summary["status"] == "no_change"
    assert summary["added"] == 0
    assert summary["unchanged"] == 1
    assert archive_digest(candidate) == archive_digest(existing)


def test_atomic_write_deja_archivo_estricto_y_sin_candidate(tmp_path):
    candidate, _ = combine_capture_archives(
        empty_archive(),
        {"laliga": _archive("laliga"), "segunda": _archive("segunda")},
        leagues=("laliga", "segunda"),
        season=2026,
    )
    target = tmp_path / "advanced_stats_snapshots.json"
    atomic_write_archive(target, candidate)
    loaded = load_archive_strict(target, require_manifest=True)
    assert len(loaded["snapshots"]) == 2
    assert not (tmp_path / "advanced_stats_snapshots.json.candidate").exists()


def test_capture_report_declara_cero_wiring_1x2():
    candidate, summary = combine_capture_archives(
        empty_archive(),
        {"laliga": _archive("laliga")},
        leagues=("laliga",),
        season=2026,
    )
    report = build_capture_report(
        target="data/advanced_stats_snapshots.json",
        merge_summary=summary,
        challenger={"laliga": {"status": "blocked", "affects_1x2": False}},
        commands=[],
    )
    assert candidate["schema"]
    assert report["affects_1x2"] is False
    assert report["production_wiring"] is False
