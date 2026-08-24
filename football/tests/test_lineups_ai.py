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


def test_clave_parsea_props():
    got = L._clave([{"j": "Lewandowski", "g": 0.6, "a": 0.2, "r": 3, "f": 1, "t": 0.3},
                    {"nope": 1}])  # el segundo se descarta (sin 'j')
    assert len(got) == 1
    assert got[0]["jugador"] == "Lewandowski"
    assert got[0]["g"] == 0.6 and got[0]["r"] == 3.0
