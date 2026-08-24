"""Ventanas, force manual, caché de intentos y metadata del proveedor."""

from datetime import datetime, timedelta

from futbol_pred.dashboard import MADRID, _ai_window, _attach_lineups, _attach_previews
from futbol_pred.ingest.preview_gemini import GeneratedPreview
import futbol_pred.ingest.ai_client as client
import futbol_pred.ingest.lineups_ai as lineups
import futbol_pred.ingest.preview_gemini as previews


def _match(now):
    return {
        "id": "m-1", "home": "A", "away": "B", "league": "LaLiga",
        "kickoff": (now + timedelta(hours=12)).isoformat(),
        "finished": False, "probs": [50, 28, 22], "xg": [1.4, 0.9],
        "markets": {"marcador": "1-0"},
    }


def test_ia_solo_manana_y_noche(monkeypatch):
    monkeypatch.delenv("FORCE_AI", raising=False)
    assert _ai_window(datetime(2026, 8, 24, 7, tzinfo=MADRID)) is True
    assert _ai_window(datetime(2026, 8, 24, 21, tzinfo=MADRID)) is True
    assert _ai_window(datetime(2026, 8, 24, 15, tzinfo=MADRID)) is False


def test_force_ai_manual_salva_ventana(monkeypatch):
    monkeypatch.setenv("FORCE_AI", "1")
    assert _ai_window(datetime(2026, 8, 24, 15, tzinfo=MADRID)) is True


def test_preview_publica_provider_real(monkeypatch):
    now = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    match = _match(now)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(client, "available", lambda: True)
    monkeypatch.setattr(previews, "generate_preview", lambda _match: GeneratedPreview(
        "texto válido", "Groq", "llama-test", 0.95
    ))
    _attach_previews([match], now)
    assert match["preview_meta"]["provider"] == "Groq"
    assert match["preview_meta"]["quality"] == 0.95


def test_fallo_lineups_solo_intenta_una_vez_por_ventana(monkeypatch):
    now = datetime(2026, 8, 24, 21, tzinfo=MADRID)
    match = _match(now)
    calls = []
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(client, "available", lambda: True)
    monkeypatch.setattr(lineups, "fetch_lineups", lambda query: calls.append(query) or {})
    _attach_lineups([match], now)
    _attach_lineups([match], now + timedelta(minutes=15))
    assert len(calls) == 1
    assert match["ai_attempts"]["lineup"]
