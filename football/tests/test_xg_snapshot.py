"""Lector de snapshot de xG por partido."""

import json


from futbol_pred.ingest.xg_snapshot import attach_xg_from_snapshot


def test_sin_fichero_es_no_op(tmp_path):
    matches = [{"home": "A", "away": "B", "date": "2026-09-13"}]
    n = attach_xg_from_snapshot(matches, "laliga", 2026, path=tmp_path / "nope.json")
    assert n == 0
    assert "stats" not in matches[0]


def test_adjunta_xg_por_partido(tmp_path):
    snap = {"schema": "xg-match-v1", "matches": [
        {"league": "laliga", "season": 2026, "date": "2026-09-13",
         "home": "FC Barcelona", "away": "Levante UD", "home_xg": 2.4, "away_xg": 0.9},
        {"league": "laliga", "season": 2026, "date": "2026-09-14",
         "home": "Real Madrid", "away": "Rayo", "home_xg": 1.8, "away_xg": 0.6},
    ]}
    path = tmp_path / "xg.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    matches = [
        {"home": "FC Barcelona", "away": "Levante UD", "date": "2026-09-13"},
        {"home": "Real Madrid", "away": "Rayo", "date": "2026-09-14"},
        {"home": "Getafe", "away": "Osasuna", "date": "2026-09-14"},  # sin xG en snapshot
    ]
    n = attach_xg_from_snapshot(matches, "laliga", 2026, path=path)
    assert n == 2
    assert matches[0]["stats"]["xg"] == [2.4, 0.9]
    assert matches[1]["stats"]["xg"] == [1.8, 0.6]
    assert "stats" not in matches[2] or "xg" not in matches[2].get("stats", {})


def test_empareja_por_kickoff_timestamp(tmp_path):
    from datetime import datetime, timezone
    ts = datetime(2026, 9, 13, 19, 0, tzinfo=timezone.utc).timestamp()
    snap = {"matches": [{"date": "2026-09-13", "home": "A", "away": "B",
                         "home_xg": 1.1, "away_xg": 1.0}]}
    path = tmp_path / "xg.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    matches = [{"home": "A", "away": "B", "kickoff": ts}]  # sin 'date', con kickoff
    n = attach_xg_from_snapshot(matches, path=path)
    assert n == 1 and matches[0]["stats"]["xg"] == [1.1, 1.0]


def test_ignora_otra_liga_o_temporada(tmp_path):
    snap = {"matches": [{"league": "segunda", "season": 2025, "date": "2026-09-13",
                         "home": "A", "away": "B", "home_xg": 1.0, "away_xg": 1.0}]}
    path = tmp_path / "xg.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    matches = [{"home": "A", "away": "B", "date": "2026-09-13"}]
    assert attach_xg_from_snapshot(matches, "laliga", 2026, path=path) == 0


def test_productor_merge_y_roundtrip(tmp_path):
    from futbol_pred.build_xg_snapshot import _merge, write_snapshot
    from futbol_pred.ingest.xg_snapshot import load_xg_snapshot
    existing = [{"league": "laliga", "season": 2026, "home": "A", "away": "B",
                 "date": "2026-09-13", "home_xg": 1.0, "away_xg": 0.5},
                {"league": "segunda", "season": 2026, "home": "C", "away": "D",
                 "date": "2026-09-13", "home_xg": 0.8, "away_xg": 0.8}]
    fresh = [{"league": "laliga", "season": 2026, "home": "E", "away": "F",
              "date": "2026-09-20", "home_xg": 2.0, "away_xg": 1.0}]
    # Reemplaza laliga 2026, conserva segunda.
    merged = _merge(existing, fresh, "laliga", 2026)
    ligas = sorted((r["league"], r["home"]) for r in merged)
    assert ligas == [("laliga", "E"), ("segunda", "C")]
    # Round-trip: escribir y volver a leer.
    path = tmp_path / "xg.json"
    write_snapshot(merged, path)
    assert len(load_xg_snapshot(path)) == 2


def test_productor_exige_soccerdata():
    # Sin soccerdata instalado, build_from_fbref debe fallar de forma explícita.
    import importlib.util
    from futbol_pred.build_xg_snapshot import build_from_fbref
    if importlib.util.find_spec("soccerdata") is not None:
        return  # entorno con soccerdata: no aplica
    try:
        build_from_fbref("laliga", 2026)
        assert False, "debería exigir soccerdata"
    except RuntimeError:
        pass
