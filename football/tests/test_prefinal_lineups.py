from datetime import datetime, timedelta
import json
from types import SimpleNamespace

from futbol_pred.prefinal_lineups import MADRID, in_prefinal_window, refresh_prefinal_lineups


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]


def _baseline(kickoff):
    return {
        "id": "m1", "home": "Local", "away": "Visitante", "kickoff": kickoff.isoformat(),
        "finished": False, "probs": [52, 28, 20],
        "alineacion": {
            "status": "probable", "provider": "Motor estadístico local",
            "local": [f"Local {i}" for i in range(11)],
            "visitante": [f"Visita {i}" for i in range(11)],
            "posiciones_local": POSITIONS, "posiciones_visitante": POSITIONS,
            "bajas_local": [], "bajas_visitante": [],
        },
    }


def _ai_response():
    return [{
        "partido": "Local - Visitante",
        "local": [{"j": f"L{i}", "pos": POSITIONS[i]} for i in range(11)],
        "visitante": [{"j": f"V{i}", "pos": POSITIONS[i]} for i in range(11)],
        "bajas_local": ["Duda Uno (duda: molestias)"],
        "bajas_visitante": [],
    }]


def test_ventana_prefinal_esta_centrada_en_t3():
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    assert in_prefinal_window(_baseline(kickoff), kickoff - timedelta(hours=3))
    assert not in_prefinal_window(_baseline(kickoff), kickoff - timedelta(hours=2))


def test_prefinal_usa_medios_como_evidencia_sin_marcar_once_oficial(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    media = [{"source": "AS", "title": "Alineación posible del Local", "published_at": now.isoformat(), "role": "probable_lineup_evidence"}]
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: media)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.available", lambda: True)
    monkeypatch.setattr(
        "futbol_pred.prefinal_lineups.chat",
        lambda *_a, **_k: SimpleNamespace(text=json.dumps(_ai_response()), provider="Gemini", model="test-model"),
    )

    report = refresh_prefinal_lineups([match], now)
    lineup = match["alineacion"]
    assert report["refreshed"] == 1
    assert report["media_grounded"] == 1
    assert lineup["phase"] == "pre_final"
    assert lineup["status"] == "probable"
    assert lineup["lineup_kind"] == "source_grounded_probable"
    assert lineup["source_quality"] == "media_grounded"
    assert lineup["media_sources"][0]["source"] == "AS"
    assert len(lineup["local"]) == len(lineup["visitante"]) == 11
    assert lineup["provider"] == "Gemini"


def test_prefinal_sin_medios_es_estimacion_y_no_probable(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: [])
    monkeypatch.setattr("futbol_pred.prefinal_lineups.available", lambda: True)
    monkeypatch.setattr(
        "futbol_pred.prefinal_lineups.chat",
        lambda *_a, **_k: SimpleNamespace(text=json.dumps(_ai_response()), provider="Gemini", model="test-model"),
    )

    report = refresh_prefinal_lineups([match], now)
    lineup = match["alineacion"]
    assert report["refreshed"] == 1
    assert report["media_grounded"] == 0
    assert lineup["status"] == "estimado"
    assert lineup["phase"] == "pre_final_estimate"
    assert lineup["lineup_kind"] == "model_estimate"
    assert lineup["source_quality"] == "model_only"
    assert "no existe una fuente externa" in lineup["display_warning"]


def test_prefinal_conserva_once_valido_si_falla_la_ia_como_estimacion(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: [])
    monkeypatch.setattr("futbol_pred.prefinal_lineups.available", lambda: False)

    report = refresh_prefinal_lineups([match], now)
    lineup = match["alineacion"]
    assert report["refreshed"] == 1
    assert report["fallback"] == 1
    assert lineup["status"] == "estimado"
    assert lineup["phase"] == "pre_final_estimate"
    assert lineup["lineup_kind"] == "fallback_estimate"
    assert lineup["source_quality"] == "statistical_fallback"
    assert len(lineup["local"]) == 11
