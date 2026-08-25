"""Parseo de onces/bajas y rechazo de alineaciones parciales."""

import json

from futbol_pred.ingest.ai_client import AIResponse
import futbol_pred.ingest.lineups_ai as L


def _props(prefix):
    """Payload legado/malicioso que el parser debe ignorar."""
    return [
        {"j": f"{prefix} {i}", "g": 0.3, "a": 0.2, "r": 2.4, "rp": 1.1,
         "fc": 1.2, "fr": 1.4, "t": 0.2}
        for i in range(1, 4)
    ]


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]


def _item(n_local=11, structured=True):
    local = [f"Local {i}" for i in range(n_local)]
    visitor = [f"Visitante {i}" for i in range(11)]
    if structured:
        local = [{"j": name, "pos": POSITIONS[i]} for i, name in enumerate(local)]
        visitor = [{"j": name, "pos": POSITIONS[i]} for i, name in enumerate(visitor)]
    return {
        "partido": "A vs B",
        "local": local,
        "visitante": visitor,
        "bajas_local": [],
        "bajas_visitante": ["Jugador lesionado"],
        "clave_local": _props("Clave local"),
        "clave_visitante": _props("Clave visitante"),
    }


def test_extract_json_con_fences_y_prosa():
    assert L._extract_json('```json\n[{"partido":"A vs B"}]\n```') == [{"partido": "A vs B"}]
    assert L._extract_json('texto [{"partido":"C vs D"}] cola')[0]["partido"] == "C vs D"
    assert L._extract_json("sin json") is None


def test_fetch_parsea_once_provider_y_descarta_props_numericas_ia(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: AIResponse(
        json.dumps([_item()]), "Groq", "llama-test"
    ))
    result = L.fetch_lineups([{"partido": "A vs B"}])["A vs B"]
    assert len(result["local"]) == len(result["visitante"]) == 11
    assert result["provider"] == "Groq" and result["model"] == "llama-test"
    assert result["clave_local"] == []
    assert result["clave_visitante"] == []
    assert result["numeric_props_source"] == "pending_real_data"
    assert result["quality"]["props_players"] == 0
    assert result["quality"]["complete"] is True
    assert result["posiciones_local"] == POSITIONS
    assert result["formacion_local"] == "4-3-3"
    assert result["quality"]["positions_players"] == 22


def test_formato_legado_infiere_posiciones_sin_dejar_huecos(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: AIResponse(
        json.dumps([_item(structured=False)]), "Gemini", "gemini-test"
    ))
    result = L.fetch_lineups([{"partido": "A vs B"}])["A vs B"]
    assert result["posiciones_local"] == POSITIONS
    assert result["formacion_visitante"] == "4-3-3"
    assert result["clave_local"] == []


def test_normaliza_demarcaciones_en_espanol_e_ingles():
    assert L._position("Goalkeeper") == "POR"
    assert L._position("lateral izquierdo") == "LI"
    assert L._position("centre-back") == "DFC"
    assert L._position("extremo derecho") == "ED"


def test_fetch_rechaza_once_parcial(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: AIResponse(
        json.dumps([_item(n_local=10)]), "Gemini", "gemini-test"
    ))
    assert L.fetch_lineups([{"partido": "A vs B"}]) == {}


def test_fetch_lista_vacia_no_llama_ia(monkeypatch):
    monkeypatch.setattr(L, "chat", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))
    assert L.fetch_lineups([]) == {}


def test_motor_local_publica_posiciones_y_formacion_sin_props_inventados():
    squad = [
        {"name": f"Jugador {i}", "position": "Goalkeeper" if i == 0 else
         "Defence" if i < 5 else "Midfield" if i < 8 else "Offence"}
        for i in range(15)
    ]
    result = L.build_statistical_lineup({"xg": [1.2, 0.8]}, squad, squad)
    assert result["posiciones_local"] == POSITIONS
    assert result["formacion_local"] == "4-3-3"
    assert result["quality"]["positions_players"] == 22
    assert result["clave_local"] == result["clave_visitante"] == []
    assert result["numeric_props_source"] == "pending_real_data"
