from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.stat_champion_evaluation import (
    SCHEMA,
    build_report,
    season_window,
    semantic_hash,
    write_report,
)


def _history(n: int = 120) -> list[MatchStats]:
    start = datetime(2024, 1, 1, 18, 0, tzinfo=timezone.utc)
    rows: list[MatchStats] = []
    for index in range(n):
        # Variación causal suficiente para que los tres métodos puedan evaluarse.
        home_fouls = 9 + (index % 5)
        away_fouls = 11 + ((index * 2) % 5)
        home_yellows = 1 + (index % 4)
        away_yellows = 2 + ((index + 1) % 4)
        rows.append(MatchStats(
            "Barcelona" if index % 2 == 0 else "Real Madrid",
            "Real Madrid" if index % 2 == 0 else "Barcelona",
            {
                "fouls": (float(home_fouls), float(away_fouls)),
                "yellows": (float(home_yellows), float(away_yellows)),
            },
            referee="Ref Test",
            kickoff=start + timedelta(days=index),
        ))
    return rows


def _audit(*seasons: int, status: str = "ok") -> list[dict]:
    return [
        {"season": season, "status": status, "rows": 40 if status == "ok" else 0}
        for season in seasons
    ]


def test_season_window_es_determinista():
    assert season_window(2026, 3) == [2024, 2025, 2026]
    assert season_window(2026, 1) == [2026]


def test_report_es_independiente_del_quality_gate_y_del_1x2():
    report = build_report(
        {"laliga": _history(), "segunda": _history()},
        {
            "laliga": _audit(2024, 2025, 2026),
            "segunda": _audit(2024, 2025, 2026),
        },
        current_season=2026,
        history_seasons=3,
    )
    assert report["schema"] == SCHEMA
    assert report["quality_gate_independent"] is True
    assert report["automatic_production_promotion"] is False
    assert report["affects_pseudo_xg"] is False
    assert report["affects_1x2"] is False
    assert report["affects_production"] is False
    assert report["summary"]["source_complete"] is True
    assert report["team_stat_rows"]
    for row in report["team_stat_rows"]:
        assert row["stat"] in {"fouls", "yellows"}
        assert "ataque_defensa" in row["methods"]
        assert row["selected_method"] in {"ataque_defensa", "regresion", "regresion_plus"}


def test_semantic_hash_no_depende_de_timestamp_operativo():
    report = build_report(
        {"laliga": _history()},
        {"laliga": _audit(2024, 2025, 2026)},
        current_season=2026,
        history_seasons=3,
    )
    first = dict(report, generated_at="2026-09-07T10:00:00+00:00")
    second = dict(report, generated_at="2026-09-07T20:00:00+00:00")
    assert semantic_hash(first) == semantic_hash(second)


def test_write_report_no_reescribe_si_el_contenido_es_identico(tmp_path):
    target = tmp_path / "report.json"
    report = build_report(
        {"laliga": _history()},
        {"laliga": _audit(2024, 2025, 2026)},
        current_season=2026,
        history_seasons=3,
    )
    first = write_report(report, target, generated_at="2026-09-07T10:00:00+00:00")
    before = target.read_text(encoding="utf-8")
    second = write_report(report, target, generated_at="2026-09-07T20:00:00+00:00")
    after = target.read_text(encoding="utf-8")
    assert first["status"] == "written"
    assert second["status"] == "unchanged"
    assert before == after


def test_fuente_degradada_preserva_ultimo_informe_bueno(tmp_path):
    target = tmp_path / "report.json"
    good = build_report(
        {"laliga": _history()},
        {"laliga": _audit(2024, 2025, 2026)},
        current_season=2026,
        history_seasons=3,
    )
    write_report(good, target, generated_at="2026-09-07T10:00:00+00:00")
    before = json.loads(target.read_text(encoding="utf-8"))

    degraded = build_report(
        {"laliga": _history(80)},
        {"laliga": [
            {"season": 2024, "status": "ok", "rows": 40},
            {"season": 2025, "status": "source_error", "rows": 0},
            {"season": 2026, "status": "ok", "rows": 40},
        ]},
        current_season=2026,
        history_seasons=3,
    )
    result = write_report(degraded, target, generated_at="2026-09-07T20:00:00+00:00")
    after = json.loads(target.read_text(encoding="utf-8"))
    assert result["status"] == "source_degraded_preserved_last_good"
    assert before == after
