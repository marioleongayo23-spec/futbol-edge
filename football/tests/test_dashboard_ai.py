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


def test_ia_solo_a_las_00_y_10(monkeypatch):
    monkeypatch.delenv("FORCE_AI", raising=False)
    assert _ai_window(datetime(2026, 8, 24, 0, 15, tzinfo=MADRID)) is True
    assert _ai_window(datetime(2026, 8, 24, 10, 15, tzinfo=MADRID)) is True
    assert _ai_window(datetime(2026, 8, 24, 7, tzinfo=MADRID)) is False
    assert _ai_window(datetime(2026, 8, 24, 15, tzinfo=MADRID)) is False


def test_force_ai_manual_salva_ventana(monkeypatch):
    monkeypatch.setenv("FORCE_AI", "1")
    assert _ai_window(datetime(2026, 8, 24, 15, tzinfo=MADRID)) is True


def test_preview_publica_provider_real(monkeypatch):
    now = datetime(2026, 8, 24, 10, 15, tzinfo=MADRID)
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
    now = datetime(2026, 8, 24, 10, 15, tzinfo=MADRID)
    match = _match(now)
    calls = []
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(client, "available", lambda: True)
    monkeypatch.setattr(lineups, "fetch_lineups", lambda query: calls.append(query) or {})
    _attach_lineups([match], now)
    _attach_lineups([match], now + timedelta(minutes=15))
    assert len(calls) == 1
    assert match["ai_attempts"]["lineup"]


def test_fuera_de_ventana_nunca_deja_previa_vacia(monkeypatch):
    now = datetime(2026, 8, 24, 15, tzinfo=MADRID)
    match = _match(now)
    match["stats"] = {
        "shots": {"home": 12, "away": 9}, "sot": {"home": 4, "away": 3},
        "corners": {"total": 9}, "fouls": {"total": 25}, "yellows": {"total": 4},
    }
    monkeypatch.delenv("FORCE_AI", raising=False)
    _attach_previews([match], now)
    assert len(match["preview"].split()) >= 90
    assert match["preview_meta"]["provider"] == "Motor estadístico local"


def test_fuera_de_ventana_rellena_once_con_plantilla_sin_inventar_props(monkeypatch):
    now = datetime(2026, 8, 24, 15, tzinfo=MADRID)
    match = _match(now)
    match["stats"] = {
        "shots": {"home": 12, "away": 9}, "sot": {"home": 4, "away": 3},
        "fouls": {"home": 13, "away": 12}, "yellows": {"home": 2.2, "away": 2},
    }
    squad = [
        {"name": f"Jugador {i}", "position": "Goalkeeper" if i == 0 else "Defence" if i < 5 else "Midfield" if i < 8 else "Offence"}
        for i in range(15)
    ]
    monkeypatch.delenv("FORCE_AI", raising=False)
    _attach_lineups([match], now, squads={"A": squad, "B": squad})
    assert len(match["alineacion"]["local"]) == 11
    assert len(match["alineacion"]["visitante"]) == 11
    assert match["alineacion"]["provider"] == "Motor estadístico local"
    assert match["alineacion"]["model"] == "squad-only-v3"
    assert match["alineacion"]["clave_local"] == []
    assert match["alineacion"]["clave_visitante"] == []
    assert match["alineacion"]["numeric_props_source"] == "pending_real_data"


def test_fuera_de_ventana_no_consume_ia_si_falta_once(monkeypatch):
    now = datetime(2026, 8, 24, 15, tzinfo=MADRID)
    match = _match(now)
    props = [{"jugador": f"Clave {i}", "g": .2, "a": .1, "r": 2, "rp": 1,
              "fc": 1, "fr": 1, "t": .1} for i in range(3)]
    generated = {
        "A vs B": {
            "local": [f"A {i}" for i in range(11)],
            "visitante": [f"B {i}" for i in range(11)],
            "bajas_local": [], "bajas_visitante": [],
            "clave_local": props, "clave_visitante": props,
            "provider": "Groq", "model": "llama-test", "quality": {"score": 1.0},
        }
    }
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(client, "available", lambda: True)
    calls = []
    monkeypatch.setattr(lineups, "fetch_lineups", lambda query: calls.append(query) or generated)
    _attach_lineups([match], now, squads={})
    assert "alineacion" not in match
    assert calls == []


def test_descarta_once_legacy_squad_stats_v1(monkeypatch):
    """Un once cacheado de un modelo legacy (plantilla de temporadas pasadas)
    se descarta para reconstruirlo; un once oficial confirmado se conserva."""
    now = datetime(2026, 8, 29, 9, 0, tzinfo=MADRID)
    monkeypatch.setattr(client, "available", lambda: False)

    legacy = _match(now)
    legacy["alineacion"] = {
        "model": "squad-stats-v1", "status": "estimado",
        "local": [f"Viejo{i}" for i in range(11)], "visitante": [f"V{i}" for i in range(11)],
    }
    official = _match(now)
    official["id"] = "m-2"
    official["alineacion"] = {
        "model": "squad-stats-v1", "status": "confirmado",
        "local": [f"Real{i}" for i in range(11)], "visitante": [f"W{i}" for i in range(11)],
    }

    _attach_lineups([legacy, official], now, squads={})

    # El once legacy no confirmado se descarta (no arrastra jugadores viejos).
    assert (legacy.get("alineacion") or {}).get("model") != "squad-stats-v1"
    # El once oficial confirmado se conserva intacto (histórico para "último XI").
    assert official["alineacion"]["status"] == "confirmado"
    assert official["alineacion"]["local"][0] == "Real0"
