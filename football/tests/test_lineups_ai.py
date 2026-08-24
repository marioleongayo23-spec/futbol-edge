"""Parseo y degradación del módulo de alineaciones IA (grounding)."""

import futbol_pred.ingest.lineups_ai as L


def test_extract_json_con_fences_y_prosa():
    assert L._extract_json('```json\n[{"partido":"A vs B","local":["x"],"visitante":["y"]}]\n```') == [
        {"partido": "A vs B", "local": ["x"], "visitante": ["y"]}
    ]
    assert L._extract_json('texto [{"partido":"C vs D"}] cola')[0]["partido"] == "C vs D"
    assert L._extract_json("sin json") is None


def test_fetch_sin_clave(monkeypatch):
    monkeypatch.setattr(L, "API_KEY", None)
    assert L.fetch_lineups([{"partido": "A vs B"}]) == {}


def test_fetch_lista_vacia():
    assert L.fetch_lineups([]) == {}
