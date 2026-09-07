import json

from futbol_pred import advanced_outcome_report as report


def test_sin_archivo_avanzado_bloquea_sin_hacer_llamadas_externas(tmp_path, monkeypatch):
    archive = tmp_path / "advanced.json"
    archive.write_text(
        json.dumps({"schema": "advanced-stats-archive-v1", "snapshots": []}),
        encoding="utf-8",
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("no debe consultar fixtures sin evidencia avanzada")

    monkeypatch.setattr(report, "get_fixtures", forbidden)
    result = report.build_league_report("laliga", 2026, archive_path=archive)

    assert result["status"] == "blocked_insufficient_advanced_snapshots"
    assert result["external_calls_skipped"] is True
    assert result["archive_snapshots"] == 0
    assert result["affects_1x2"] is False


def test_snapshot_de_otra_liga_no_desbloquea_llamadas(tmp_path, monkeypatch):
    archive = tmp_path / "advanced.json"
    archive.write_text(
        json.dumps(
            {
                "schema": "advanced-stats-archive-v1",
                "snapshots": [
                    {
                        "schema": "advanced-stats-snapshot-v1",
                        "source": "test",
                        "available_at": "2026-08-01T12:00:00+00:00",
                        "league": "segunda",
                        "season": 2026,
                        "teams": {
                            "Albacete": {"matches": 1, "xg_for90": 1.0, "xg_against90": 1.0},
                            "Zaragoza": {"matches": 1, "xg_for90": 1.0, "xg_against90": 1.0},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        report,
        "get_fixtures",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no call")),
    )
    result = report.build_league_report("laliga", 2026, archive_path=archive)
    assert result["status"] == "blocked_insufficient_advanced_snapshots"
    assert result["external_calls_skipped"] is True


def test_market_baseline_elimina_vig_y_conserva_clave_del_record():
    base = [
        {
            "round": ("league", "REGULAR", 2026, 1),
            "home": "FC Barcelona",
            "away": "RCD Espanyol",
            "actual": "1",
            "kickoff": 1.0,
            "probs": {"1": 0.5, "X": 0.3, "2": 0.2},
        }
    ]
    closing = [
        {
            "home": "Barcelona",
            "away": "RCD Espanyol",
            "closing_odds": {"1x2": {"1": 1.8, "X": 3.8, "2": 5.0}},
        }
    ]

    records, coverage = report.market_baseline_records(base, closing)
    assert coverage["complete"] is True
    assert len(records) == 1
    assert records[0]["round"] == base[0]["round"]
    assert abs(sum(records[0]["probs"].values()) - 1.0) < 1e-9
    assert records[0]["probs"]["1"] > records[0]["probs"]["X"] > records[0]["probs"]["2"]
    assert records[0]["baseline_source"].endswith("closing no-vig")


def test_closing_ambiguo_no_se_usa_como_comparador():
    base = [
        {
            "round": ("league", "REGULAR", 2026, 1),
            "home": "Barcelona",
            "away": "RCD Espanyol",
            "actual": "1",
            "kickoff": 1.0,
            "probs": {"1": 0.5, "X": 0.3, "2": 0.2},
        }
    ]
    closing = [
        {
            "home": "FC Barcelona",
            "away": "RCD Espanyol",
            "closing_odds": {"1x2": {"1": 1.8, "X": 3.8, "2": 5.0}},
        },
        {
            "home": "Barcelona",
            "away": "RCD Espanyol",
            "closing_odds": {"1x2": {"1": 1.9, "X": 3.7, "2": 4.8}},
        },
    ]
    records, coverage = report.market_baseline_records(base, closing)
    assert records == []
    assert coverage["complete"] is False
    assert coverage["ambiguous_pairs"] == 1


def test_build_report_declara_explicitamente_cero_impacto(tmp_path):
    archive = tmp_path / "advanced.json"
    archive.write_text(
        json.dumps({"schema": "advanced-stats-archive-v1", "snapshots": []}),
        encoding="utf-8",
    )
    payload = report.build_report(
        leagues=("laliga",),
        season=2026,
        archive_path=archive,
    )
    assert payload["schema"] == "advanced-outcome-challenger-report-v1"
    assert payload["affects_1x2"] is False
    assert payload["reports"]["laliga"]["accepted"] is False
