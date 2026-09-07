import json
from datetime import datetime

from futbol_pred.final_stats_truth import (
    SOURCE_API,
    SOURCE_FDUK,
    build_observations,
    empty_archive,
    match_id,
    refresh_truth_store,
    update_archive,
)
from futbol_pred.ingest.football_data_uk import MatchStats


def _match(source="API-Football · final", shots=(16, 9), xg=(2.05, 0.74)):
    stats = {
        "goals": {"home": 2, "away": 1, "total": 3},
        "shots": {"home": shots[0], "away": shots[1], "total": sum(shots)},
        "sot": {"home": 7, "away": 3, "total": 10},
        "corners": {"home": 8, "away": 4, "total": 12},
        "fouls": {"home": 11, "away": 15, "total": 26},
        "yellows": {"home": 2, "away": 4, "total": 6},
        "reds": {"home": 0, "away": 1, "total": 1},
    }
    if xg is not None:
        stats["xg"] = {"home": xg[0], "away": xg[1], "total": sum(xg)}
    return {
        "id": "m1",
        "league": "LaLiga",
        "home": "Barcelona",
        "away": "RCD Espanyol",
        "kickoff": "2026-08-20T21:00:00+02:00",
        "finished": True,
        "result": [2, 1],
        "statsRealSource": source,
        "statsRealUpdatedAt": "2026-08-20T23:05:00+02:00",
        "statsReal": stats,
        "alineacion": {"official_fixture_id": 77},
    }


def _fduk(shots=(16, 9), home="Barcelona", away="Espanyol"):
    return MatchStats(
        home,
        away,
        {
            "goals": (2, 1),
            "shots": shots,
            "sot": (7, 3),
            "corners": (8, 4),
            "fouls": (11, 15),
            "yellows": (2, 4),
            "reds": (0, 1),
            "offsides": (3, 2),
        },
        referee="Árbitro X",
        kickoff=datetime.fromisoformat("2026-08-20T21:00:00+02:00"),
    )


def test_match_id_usa_identidad_canonica_y_no_mezcla_espanyol():
    a = match_id("laliga", 2026, "2026-08-20T21:00:00+02:00", "FC Barcelona", "Espanyol")
    b = match_id("laliga", 2026, "2026-08-20T21:00:00+02:00", "Barcelona", "RCD Espanyol")
    c = match_id("laliga", 2026, "2026-08-20T21:00:00+02:00", "RCD Espanyol", "Barcelona")
    assert a == b
    assert a != c


def test_build_observations_emite_ambas_fuentes_con_match_id_comun():
    rows, audit = build_observations(
        [_match()],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk()],
        captured_at="2026-08-21T08:00:00Z",
    )
    assert len(rows) == 2
    assert {row["source"] for row in rows} == {SOURCE_API, SOURCE_FDUK}
    assert len({row["match_id"] for row in rows}) == 1
    assert audit["api_matches"] == 1
    assert audit["football_data_uk_matches"] == 1
    api = next(row for row in rows if row["source"] == SOURCE_API)
    fduk = next(row for row in rows if row["source"] == SOURCE_FDUK)
    assert api["stats"]["xg"] == {"home": 2.05, "away": 0.74, "total": 2.79}
    assert "xg" not in fduk["stats"]


def test_fduk_ambiguo_no_se_elige_silenciosamente():
    rows, audit = build_observations(
        [_match(source="football-data.co.uk")],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk(), _fduk()],
        captured_at="2026-08-21T08:00:00Z",
    )
    assert rows == []
    assert audit["ambiguous_football_data_uk_matches"] == 1


def test_doble_fuente_igual_queda_verificada_y_xg_single_source():
    observations, _ = build_observations(
        [_match()],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk()],
        captured_at="2026-08-21T08:00:00Z",
    )
    archive, summary = update_archive(
        empty_archive(), observations, updated_at="2026-08-21T08:00:00Z"
    )
    entry = next(iter(archive["matches"].values()))
    assert entry["status"] == "verified_multi_source"
    assert entry["consensus"]["shots"]["status"] == "agreed"
    assert entry["consensus"]["shots"]["usable"] is True
    assert entry["consensus"]["xg"]["status"] == "single_source"
    assert entry["consensus"]["xg"]["sources"] == [SOURCE_API]
    assert entry["consensus"]["xg"]["confidence"] == 0.6
    assert entry["consensus"]["offsides"]["status"] == "single_source"
    assert entry["consensus"]["offsides"]["sources"] == [SOURCE_FDUK]
    assert summary["usable_by_stat"]["xg"] == 1
    assert summary["added_revisions"] == 2
    assert summary["affects_1x2"] is False


def test_xg_ausente_simplemente_no_aparece_en_truth_store():
    observations, _ = build_observations(
        [_match(xg=None)],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk()],
        captured_at="2026-08-21T08:00:00Z",
    )
    archive, _ = update_archive(empty_archive(), observations, updated_at="2026-08-21T08:00:00Z")
    entry = next(iter(archive["matches"].values()))
    assert "xg" not in entry["consensus"]
    assert "xg" not in (archive.get("quality") or {}).get("usable_by_stat", {})


def test_conflicto_no_elige_un_proveedor_y_marca_unusable():
    observations, _ = build_observations(
        [_match(shots=(16, 9))],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk(shots=(15, 9))],
        captured_at="2026-08-21T08:00:00Z",
    )
    archive, summary = update_archive(
        empty_archive(), observations, updated_at="2026-08-21T08:00:00Z"
    )
    entry = next(iter(archive["matches"].values()))
    shots = entry["consensus"]["shots"]
    assert entry["status"] == "conflict"
    assert shots["status"] == "conflict"
    assert shots["usable"] is False
    assert "home" not in shots  # no existe un valor elegido silenciosamente
    assert summary["conflicts_by_stat"]["shots"] == 1


def test_misma_observacion_con_otro_timestamp_no_crea_revision():
    observations, _ = build_observations(
        [_match()], league="laliga", season=2026, fduk_rows=[], captured_at="2026-08-21T08:00:00Z"
    )
    archive, first = update_archive(empty_archive(), observations, updated_at="2026-08-21T08:00:00Z")
    later = [dict(row, captured_at="2026-08-22T08:00:00Z") for row in observations]
    archive2, second = update_archive(archive, later, updated_at="2026-08-22T08:00:00Z")
    entry = next(iter(archive2["matches"].values()))
    assert first["added_revisions"] == 1
    assert second["added_revisions"] == 0
    assert second["unchanged_observations"] == 1
    assert len(entry["sources"][SOURCE_API]["history"]) == 1
    assert archive2["updated_at"] == "2026-08-21T08:00:00Z"


def test_correccion_posterior_del_proveedor_conserva_revision_anterior():
    first_obs, _ = build_observations(
        [_match(shots=(16, 9))], league="laliga", season=2026, fduk_rows=[], captured_at="2026-08-21T08:00:00Z"
    )
    archive, _ = update_archive(empty_archive(), first_obs, updated_at="2026-08-21T08:00:00Z")
    corrected_obs, _ = build_observations(
        [_match(shots=(17, 9))], league="laliga", season=2026, fduk_rows=[], captured_at="2026-08-22T08:00:00Z"
    )
    archive, summary = update_archive(archive, corrected_obs, updated_at="2026-08-22T08:00:00Z")
    entry = next(iter(archive["matches"].values()))
    history = entry["sources"][SOURCE_API]["history"]
    assert summary["added_revisions"] == 1
    assert len(history) == 2
    assert history[0]["stats"]["shots"]["home"] == 16
    assert history[1]["stats"]["shots"]["home"] == 17
    assert entry["sources"][SOURCE_API]["latest"]["stats"]["shots"]["home"] == 17


def test_refresh_store_persiste_feed_y_fduk_sin_red_real(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard.json"
    output = tmp_path / "truth.json"
    dashboard.write_text(json.dumps({"matches": [_match()]}), encoding="utf-8")

    monkeypatch.setattr(
        "futbol_pred.final_stats_truth.FootballDataUKClient.get_stats",
        lambda self, league, season: [_fduk()] if league == "laliga" else [],
    )
    report = refresh_truth_store(
        dashboard,
        output,
        season=2026,
        captured_at="2026-08-21T08:00:00Z",
    )
    assert report["status"] == "updated"
    assert report["added_revisions"] == 2
    assert report["usable_by_stat"]["xg"] == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema"] == "final-stats-truth-v1"
    assert saved["affects_1x2"] is False
    entry = next(iter(saved["matches"].values()))
    assert entry["home"] == "Barcelona"
    assert entry["away"] == "Espanol"
    assert entry["consensus"]["xg"]["sources"] == [SOURCE_API]
    assert entry["sources"][SOURCE_API]["latest"]["away_source_name"] == "RCD Espanyol"
