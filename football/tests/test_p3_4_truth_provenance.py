from datetime import datetime

from futbol_pred.final_stats_truth import SOURCE_FDUK, build_observations
from futbol_pred.finished_stats import _inherit_previous_stats
from futbol_pred.ingest.football_data_uk import MatchStats


def _stats():
    return {
        "goals": {"home": 2, "away": 1, "total": 3},
        "shots": {"home": 16, "away": 9, "total": 25},
        "sot": {"home": 7, "away": 3, "total": 10},
        "corners": {"home": 8, "away": 4, "total": 12},
        "fouls": {"home": 11, "away": 15, "total": 26},
        "yellows": {"home": 2, "away": 4, "total": 6},
        "reds": {"home": 0, "away": 1, "total": 1},
    }


def _match(source=None):
    row = {
        "id": "legacy-1",
        "league": "LaLiga",
        "home": "Barcelona",
        "away": "RCD Espanyol",
        "kickoff": "2026-08-20T21:00:00+02:00",
        "finished": True,
        "result": [2, 1],
        "statsReal": _stats(),
    }
    if source is not None:
        row["statsRealSource"] = source
    return row


def _fduk():
    return MatchStats(
        "Barcelona",
        "Espanyol",
        {
            "goals": (2, 1),
            "shots": (16, 9),
            "sot": (7, 3),
            "corners": (8, 4),
            "fouls": (11, 15),
            "yellows": (2, 4),
            "reds": (0, 1),
        },
        kickoff=datetime.fromisoformat("2026-08-20T21:00:00+02:00"),
    )


def test_migracion_legacy_etiqueta_solo_firma_historica_conocida():
    current = {"id": "legacy-1"}
    _inherit_previous_stats(current, _match())
    assert current["statsRealSource"] == "football-data.co.uk · legacy cached"
    assert current["statsRealProvenance"]["kind"] == "legacy_schema_migration"
    assert current["statsRealProvenance"]["inferred"] is True


def test_migracion_legacy_no_infiere_bloque_incompleto_o_xg():
    incomplete = _match()
    incomplete["statsReal"].pop("reds")
    current = {"id": "legacy-1"}
    _inherit_previous_stats(current, incomplete)
    assert "statsRealSource" not in current

    with_xg = _match()
    with_xg["statsReal"]["xg"] = {"home": 1.9, "away": 0.8, "total": 2.7}
    current2 = {"id": "legacy-1"}
    _inherit_previous_stats(current2, with_xg)
    assert "statsRealSource" not in current2


def test_cache_fduk_etiquetado_alimenta_truth_si_csv_cae():
    match = _match("football-data.co.uk · legacy cached")
    match["statsRealProvenance"] = {"kind": "legacy_schema_migration", "inferred": True}
    rows, audit = build_observations(
        [match],
        league="laliga",
        season=2026,
        fduk_rows=[],
        captured_at="2026-08-21T08:00:00Z",
    )
    assert len(rows) == 1
    assert rows[0]["source"] == SOURCE_FDUK
    assert rows[0]["meta"]["capture"] == "dashboard_cache"
    assert audit["cached_football_data_uk_matches"] == 1
    assert audit["football_data_uk_matches"] == 1


def test_truth_no_adivina_una_fuente_desconocida():
    rows, audit = build_observations(
        [_match()],
        league="laliga",
        season=2026,
        fduk_rows=[],
        captured_at="2026-08-21T08:00:00Z",
    )
    assert rows == []
    assert audit["cached_football_data_uk_matches"] == 0


def test_csv_vivo_exacto_tiene_prioridad_y_no_duplica_cache():
    rows, audit = build_observations(
        [_match("football-data.co.uk · legacy cached")],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk()],
        captured_at="2026-08-21T08:00:00Z",
    )
    assert len(rows) == 1
    assert rows[0]["source"] == SOURCE_FDUK
    assert rows[0]["meta"]["capture"] == "live_csv"
    assert audit["cached_football_data_uk_matches"] == 0


def test_csv_ambiguo_bloquea_cache_en_vez_de_ocultar_conflicto_identidad():
    rows, audit = build_observations(
        [_match("football-data.co.uk · legacy cached")],
        league="laliga",
        season=2026,
        fduk_rows=[_fduk(), _fduk()],
        captured_at="2026-08-21T08:00:00Z",
    )
    assert rows == []
    assert audit["ambiguous_football_data_uk_matches"] == 1
    assert audit["cached_football_data_uk_matches"] == 0
