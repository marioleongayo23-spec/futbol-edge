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


def _ai_response(local_positions=None):
    local_positions = local_positions or POSITIONS
    return [{
        "partido": "Local - Visitante",
        "local": [{"j": f"L{i}", "pos": local_positions[i]} for i in range(11)],
        "visitante": [{"j": f"V{i}", "pos": POSITIONS[i]} for i in range(11)],
        "bajas_local": ["Duda Uno (duda: molestias)"],
        "bajas_visitante": [],
    }]


def _media(now, sides=("local", "visitante")):
    rows = []
    if "local" in sides:
        rows.append({
            "source": "AS", "title": "Alineación posible del Local", "published_at": now.isoformat(),
            "role": "probable_lineup_evidence", "covered_sides": ["local"],
            "evidence_level": "trusted_media_recent", "evidence_rank": 2,
        })
    if "visitante" in sides:
        rows.append({
            "source": "MARCA", "title": "El once probable del Visitante", "published_at": now.isoformat(),
            "role": "probable_lineup_evidence", "covered_sides": ["visitante"],
            "evidence_level": "trusted_media_recent", "evidence_rank": 2,
        })
    return rows


def _mock_ai(monkeypatch, response=None):
    monkeypatch.setattr("futbol_pred.prefinal_lineups.available", lambda: True)
    monkeypatch.setattr(
        "futbol_pred.prefinal_lineups.chat",
        lambda *_a, **_k: SimpleNamespace(
            text=json.dumps(response or _ai_response()), provider="Gemini", model="test-model"
        ),
    )


def _official_history_match(kickoff, suffix):
    return {
        "id": f"old-{suffix}",
        "home": "Local",
        "away": f"Rival {suffix}",
        "kickoff": kickoff.isoformat(),
        "finished": True,
        "result": [1, 0],
        "alineacion": {
            "status": "confirmado",
            "local": [f"L{i}" for i in range(11)],
            "visitante": [f"R{suffix}-{i}" for i in range(11)],
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
        },
    }


def test_ventana_prefinal_esta_centrada_en_t3():
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    assert in_prefinal_window(_baseline(kickoff), kickoff - timedelta(hours=3))
    assert not in_prefinal_window(_baseline(kickoff), kickoff - timedelta(hours=2))


def test_prefinal_solo_es_probable_con_evidencia_de_ambos_equipos(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: _media(now))
    _mock_ai(monkeypatch)

    report = refresh_prefinal_lineups([match], now)
    lineup = match["alineacion"]
    assert report["refreshed"] == 1
    assert report["media_grounded"] == 1
    assert report["media_partial"] == 0
    assert report["probable"] == 1
    assert lineup["phase"] == "pre_final"
    assert lineup["status"] == "probable"
    assert lineup["lineup_kind"] == "source_grounded_probable"
    assert lineup["source_quality"] == "media_grounded"
    assert lineup["evidence_scope"] == "trusted_media_both_sides"
    assert lineup["lineup_evidence"]["local"]["grounded"] is True
    assert lineup["lineup_evidence"]["visitante"]["grounded"] is True
    assert lineup["lineup_evidence"]["policy"] == "both_sides_required_for_probable"
    assert len(lineup["local"]) == len(lineup["visitante"]) == 11
    assert lineup["provider"] == "Gemini"
    assert lineup["probable_refresh_window_last"] == "T-3h"


def test_una_noticia_solo_del_local_no_respalda_el_once_visitante(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: _media(now, ("local",)))
    _mock_ai(monkeypatch)

    report = refresh_prefinal_lineups([match], now)
    lineup = match["alineacion"]
    assert report["media_grounded"] == 0
    assert report["media_partial"] == 1
    assert report["probable"] == 0
    assert lineup["status"] == "estimado"
    assert lineup["phase"] == "pre_final_estimate"
    assert lineup["lineup_kind"] == "partially_grounded_estimate"
    assert lineup["source_quality"] == "media_partial"
    assert lineup["evidence_scope"] == "trusted_media_partial"
    assert lineup["lineup_evidence"]["local"]["grounded"] is True
    assert lineup["lineup_evidence"]["visitante"]["grounded"] is False
    assert "equipo visitante" in lineup["display_warning"]


def test_prefinal_infiere_lado_en_evidencia_antigua_sin_covered_sides(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    legacy = [
        {"source": "AS", "title": "Alineación posible del Local", "published_at": now.isoformat()},
        {"source": "MARCA", "title": "Once probable del Visitante", "published_at": now.isoformat()},
    ]
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: legacy)
    _mock_ai(monkeypatch)

    refresh_prefinal_lineups([match], now)
    assert match["alineacion"]["status"] == "probable"
    assert match["alineacion"]["lineup_evidence"]["level"] == "trusted_media_both_sides"


def test_prefinal_sin_medios_es_estimacion_y_no_probable(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    match = _baseline(kickoff)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: [])
    _mock_ai(monkeypatch)

    report = refresh_prefinal_lineups([match], now)
    lineup = match["alineacion"]
    assert report["refreshed"] == 1
    assert report["media_grounded"] == 0
    assert report["media_partial"] == 0
    assert report["probable"] == 0
    assert lineup["status"] == "estimado"
    assert lineup["phase"] == "pre_final_estimate"
    assert lineup["lineup_kind"] == "model_estimate"
    assert lineup["source_quality"] == "model_only"
    assert lineup["evidence_scope"] == "model_only"
    assert "ambos equipos" in lineup["display_warning"]


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


def test_refresca_probable_t8_y_t90_sin_repetir_misma_ventana(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    match = _baseline(kickoff)
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: _media(kickoff))
    _mock_ai(monkeypatch)

    report_t8 = refresh_prefinal_lineups([match], kickoff - timedelta(hours=8))
    assert report_t8["windows"] == {"T-8h": 1}
    assert match["alineacion"]["phase"] == "same_day_probable"
    assert match["alineacion"]["probable_refresh_windows"].get("T-8h")

    repeated = refresh_prefinal_lineups([match], kickoff - timedelta(hours=8))
    assert repeated["candidates"] == 0

    report_t90 = refresh_prefinal_lineups([match], kickoff - timedelta(minutes=90))
    assert report_t90["windows"] == {"T-90m": 1}
    assert match["alineacion"]["probable_refresh_windows"].get("T-90m")


def test_historial_oficial_corrige_posicion_modelo_con_dos_antecedentes(monkeypatch):
    kickoff = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    now = kickoff - timedelta(hours=3)
    target = _baseline(kickoff)
    old1 = _official_history_match(kickoff - timedelta(days=7), "a")
    old2 = _official_history_match(kickoff - timedelta(days=14), "b")

    wrong = list(POSITIONS)
    wrong[1] = "DFC"  # L1 es LI en dos XI oficiales previos.
    monkeypatch.setattr("futbol_pred.prefinal_lineups.collect_probable_lineup_media", lambda *_a, **_k: _media(now))
    _mock_ai(monkeypatch, _ai_response(wrong))

    refresh_prefinal_lineups([old2, old1, target], now)
    lineup = target["alineacion"]
    assert lineup["posiciones_local"][1] == "LI"
    assert lineup["position_source"] == "official_history+model"
    assert lineup["position_history_overrides"] >= 1
    assert any(row["player"] == "L1" and row["to"] == "LI" for row in lineup["position_history_evidence"])
