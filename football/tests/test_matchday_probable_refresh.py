from datetime import datetime, timedelta
import json
from types import SimpleNamespace

from futbol_pred.matchday_probable_refresh import MADRID, _stored_media, refresh_payload


POSITIONS = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]


def _match(kickoff):
    return {
        "id": "m1",
        "home": "Local",
        "away": "Visitante",
        "league": "LaLiga",
        "kickoff": kickoff.isoformat(),
        "finished": False,
        "probs": [55, 25, 20],
        "alineacion": {
            "status": "estimado",
            "source_quality": "model_only",
            "local": [f"L{i}" for i in range(11)],
            "visitante": [f"V{i}" for i in range(11)],
            "posiciones_local": POSITIONS,
            "posiciones_visitante": POSITIONS,
            "clave_local": [],
            "clave_visitante": [],
        },
        "matchday_player_rates": {
            "checked_at": (kickoff - timedelta(hours=2)).isoformat(),
            "source": "API-Football · players",
            "local": [{"player": f"L{i}"} for i in range(11)],
            "visitante": [{"player": f"V{i}"} for i in range(11)],
        },
    }


class OfflineClient:
    offline = True


def _media(now):
    return [
        {
            "source": "AS", "title": "Alineación posible del Local", "published_at": now.isoformat(),
            "covered_sides": ["local"], "evidence_level": "trusted_media_recent", "evidence_rank": 2,
            "analysis_text": "El técnico mantendrá el bloque titular del último encuentro.",
        },
        {
            "source": "MARCA", "title": "Once probable del Visitante", "published_at": now.isoformat(),
            "covered_sides": ["visitante"], "evidence_level": "trusted_media_recent", "evidence_rank": 2,
            "analysis_text": "No se esperan cambios relevantes en el once visitante.",
        },
    ]


def _ai_rows(with_positions=True):
    def rows(prefix):
        if with_positions:
            return [{"j": f"{prefix}{i}", "pos": POSITIONS[i]} for i in range(11)]
        return [f"{prefix}{i}" for i in range(11)]
    return [{
        "partido": "Local - Visitante",
        "local": rows("L"),
        "visitante": rows("V"),
        "bajas_local": [],
        "bajas_visitante": [],
    }]


def _fake_props(starters, _rates, limit=11):
    return [
        {
            "jugador": name,
            "g": 0.2, "a": 0.1, "r": 1.8, "rp": 0.7,
            "fc": 1.0, "fr": 1.1, "t": 0.15,
            "min": 78.0, "tit": 1.0,
            "sample_minutes": 90,
            "source": "API-Football · players",
        }
        for name in starters[:limit]
    ]


def test_t48_reinvestiga_medios_y_recalcula_props(monkeypatch):
    kickoff = datetime(2026, 8, 26, 21, tzinfo=MADRID)
    now = kickoff - timedelta(minutes=48)
    match = _match(kickoff)
    payload = {"matches": [match], "source_health": {"api_football": {"daily_remaining": 50}}}

    monkeypatch.setattr("futbol_pred.matchday_probable_refresh.collect_probable_lineup_media", lambda *_a, **_k: _media(now))
    monkeypatch.setattr("futbol_pred.matchday_probable_refresh._enrich_media", lambda rows: rows)
    monkeypatch.setattr("futbol_pred.matchday_probable_refresh.available", lambda: True)
    monkeypatch.setattr(
        "futbol_pred.matchday_probable_refresh.chat",
        lambda *_a, **_k: SimpleNamespace(text=json.dumps(_ai_rows()), provider="Gemini", model="test"),
    )
    monkeypatch.setattr("futbol_pred.matchday_probable_refresh.player_api.props_for_official_starters", _fake_props)

    changed, report = refresh_payload(payload, now=now, football_client=OfflineClient())
    lineup = match["alineacion"]
    assert changed is True
    assert report["media_checked"] == 1
    assert report["probable_refreshed"] == 1
    assert lineup["status"] == "probable"
    assert lineup["probable_refresh_window_last"] == "T-48m"
    assert lineup["critical_probable_checked_at"]
    assert lineup["player_props_checked_at"]
    assert len(lineup["clave_local"]) == 11
    assert len(lineup["clave_visitante"]) == 11
    assert lineup["clave_local"][0]["sample_quality"] == "baja_inicio_temporada"
    assert match["operational_checks"]["player_props_check_result"] == "ok"


def test_t48_rechaza_xi_sin_posiciones_explicitas(monkeypatch):
    kickoff = datetime(2026, 8, 26, 21, tzinfo=MADRID)
    now = kickoff - timedelta(minutes=48)
    match = _match(kickoff)
    payload = {"matches": [match]}

    monkeypatch.setattr("futbol_pred.matchday_probable_refresh.collect_probable_lineup_media", lambda *_a, **_k: _media(now))
    monkeypatch.setattr("futbol_pred.matchday_probable_refresh._enrich_media", lambda rows: rows)
    monkeypatch.setattr("futbol_pred.matchday_probable_refresh.available", lambda: True)
    monkeypatch.setattr(
        "futbol_pred.matchday_probable_refresh.chat",
        lambda *_a, **_k: SimpleNamespace(text=json.dumps(_ai_rows(False)), provider="Gemini", model="test"),
    )
    monkeypatch.setattr("futbol_pred.matchday_probable_refresh.player_api.props_for_official_starters", _fake_props)

    _, report = refresh_payload(payload, now=now, football_client=OfflineClient())
    assert report["media_checked"] == 1
    assert report["probable_refreshed"] == 0
    assert match["alineacion"]["status"] == "estimado"
    assert match["alineacion"]["critical_probable_checked_at"]


def test_cuerpo_articulo_no_se_persiste_en_feed():
    rows = [{
        "source": "AS",
        "title": "Once probable",
        "analysis_text": "Texto completo usado solo para análisis",
        "article_modified_at": "2026-08-26T19:00:00+02:00",
    }]
    stored = _stored_media(rows)
    assert "analysis_text" not in stored[0]
    assert stored[0]["article_modified_at"]
