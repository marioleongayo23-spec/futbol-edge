"""Parseo, props ampliadas y rechazo de alineaciones parciales."""

import json

from futbol_pred.ingest.ai_client import AIResponse
import futbol_pred.ingest.lineups_ai as L


def _props(prefix):
    return [
        {"j": f"{prefix} {i}", "g": 0.3, "a": 0.2, "r": 2.4, "rp": 1.1,
         "fc": 1.2, "fr": 1.4, "t": 0.2}
        for i in range(1, 4)
    ]


def _item(n_local=11):
    return {
        "partido": "A vs B",
        "local": [f"Local {i}" for i in range(n_local)],
        "visitante": [f"Visitante {i}" for i in range(11)],
        "bajas_local": [],
        "bajas_visitante": ["Jugador lesionado"],
        "clave_local": _props("Clave local"),
        "clave_visitante": _props("Clave visitante"),
    }


def test_extract_json_con_fences_y_prosa():
    assert L._extract_json('```json\n[{"partido":"A vs B"}]\n```') == [{"partido": "A vs B"}]
    assert L._extract_json('texto [{"partido":"C vs D"}] cola')[0]["partido"] == "C vs D"
    assert L._extract_json("sin json") is None


def test_fetch_parsea_props_ampliadas_y_provider(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: AIResponse(
        json.dumps([_item()]), "Groq", "llama-test"
    ))
    result = L.fetch_lineups([{"partido": "A vs B"}])["A vs B"]
    assert len(result["local"]) == len(result["visitante"]) == 11
    assert result["provider"] == "Groq" and result["model"] == "llama-test"
    assert result["clave_local"][0]["rp"] == 1.1
    assert result["clave_local"][0]["fc"] == 1.2
    assert result["clave_local"][0]["fr"] == 1.4
    assert result["quality"]["complete"] is True


def test_fetch_rechaza_once_parcial(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: AIResponse(
        json.dumps([_item(n_local=10)]), "Gemini", "gemini-test"
    ))
    assert L.fetch_lineups([{"partido": "A vs B"}]) == {}


def test_fetch_lista_vacia_no_llama_ia(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    assert L.fetch_lineups([]) == {}
