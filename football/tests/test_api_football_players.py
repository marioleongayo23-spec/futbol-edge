from datetime import datetime, timedelta

import pytest

from futbol_pred.dashboard import MADRID
from futbol_pred.ingest.api_football_players import (
    MIN_PLAYER_MINUTES,
    fetch_team_player_rates,
    props_for_official_starters,
)
from futbol_pred.operational import attach_official_context


def _player(name, minutes=900, appearances=12, starts=10, shots=30, sot=14, goals=5, assists=3, fc=12, fr=18, yellow=2):
    return {
        "player": {
            "id": abs(hash(name)) % 100000,
            "name": name,
            "age": 27,
            "nationality": "Spain",
            "height": "181 cm",
            "weight": "75 kg",
            "photo": f"https://media.api-sports.io/football/players/{abs(hash(name)) % 100000}.png",
            "birth": {"date": "1999-02-03", "place": "Madrid", "country": "Spain"},
        },
        "statistics": [{
            "league": {"id": 140},
            "games": {
                "minutes": minutes, "appearences": appearances, "lineups": starts,
                "position": "Midfielder", "rating": "7.21",
            },
            "shots": {"total": shots, "on": sot},
            "goals": {"total": goals, "assists": assists, "saves": 0},
            "fouls": {"committed": fc, "drawn": fr},
            "cards": {"yellow": yellow},
            "passes": {"total": 520, "key": 24, "accuracy": "86"},
            "tackles": {"total": 31, "blocks": 8, "interceptions": 19},
            "duels": {"total": 110, "won": 64},
            "dribbles": {"attempts": 38, "success": 21},
            "offsides": 3,
            "penalty": {"won": 1, "commited": 0, "scored": 1, "missed": 0, "saved": 0},
        }],
    }


class PlayerClient:
    offline = False

    def __init__(self):
        self.calls = []

    def _get(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "teams":
            return {"response": [{"team": {"id": 10, "name": "Real Team"}}]}
        if path == "players":
            return {
                "response": [
                    _player("Titular Uno"),
                    _player("Titular Dos", shots=18, sot=7, goals=2),
                    _player("Sin muestra", minutes=MIN_PLAYER_MINUTES - 1),
                ],
                "paging": {"total": 1},
            }
        raise AssertionError(path)


def test_rates_requieren_muestra_y_se_cachean_por_equipo():
    client = PlayerClient()
    first = fetch_team_player_rates(client, "Real Team", 2026, 140)
    second = fetch_team_player_rates(client, "Real Team", 2026, 140)

    assert [row["player"] for row in first] == ["Titular Uno", "Titular Dos"]
    assert second == first
    assert len(client.calls) == 2  # teams + players solo una vez
    assert first[0]["per90"]["r"] == pytest.approx(3.0)
    assert first[0]["source"] == "API-Football · players"


def test_rates_retienen_perfil_y_metricas_de_rol_para_fichas_visuales():
    row = fetch_team_player_rates(PlayerClient(), "Real Team", 2026, 140)[0]

    assert row["profile"]["photo"].startswith("https://media.api-sports.io/")
    assert row["profile"]["age"] == 27
    assert row["profile"]["nationality"] == "Spain"
    assert row["profile"]["height"] == "181 cm"
    assert row["profile"]["birth_date"] == "1999-02-03"
    assert row["position"] == "Midfielder"
    assert row["rating"] == pytest.approx(7.21)
    assert row["pass_accuracy_pct"] == pytest.approx(86.0)
    assert row["per90_extended"]["passes"] == pytest.approx(52.0)
    assert row["per90_extended"]["key_passes"] == pytest.approx(2.4)
    assert row["per90_extended"]["interceptions"] == pytest.approx(1.9)
    assert row["per90_extended"]["duels_won"] == pytest.approx(6.4)
    assert row["per90_extended"]["dribbles_success"] == pytest.approx(2.1)


def test_props_oficiales_usan_tasas_por_90_y_titularidad_uno():
    rates = [{
        "player": "Álex Uno", "player_id": 8, "minutes": 900, "expected_start_minutes": 75.0,
        "position": "Forward", "rating": 7.34, "pass_accuracy_pct": 81.0,
        "profile": {"photo": "https://example.com/alex.png", "age": 25},
        "per90": {"g": 0.5, "a": 0.2, "r": 3.0, "rp": 1.5, "fc": 1.2, "fr": 1.8, "t": 0.2},
        "per90_extended": {"key_passes": 1.8, "duels_won": 4.2, "dribbles_success": 2.4},
        "source": "API-Football · players",
    }]
    props = props_for_official_starters(["Alex Uno"], rates)
    assert len(props) == 1
    assert props[0]["tit"] == 1.0
    assert props[0]["min"] == 75.0
    assert props[0]["r"] == pytest.approx(2.5)
    assert props[0]["sample_minutes"] == 900
    assert props[0]["player_id"] == 8
    assert props[0]["profile"]["photo"] == "https://example.com/alex.png"
    assert props[0]["rating"] == pytest.approx(7.34)
    assert props[0]["extended"]["key_passes"] == pytest.approx(1.5)
    assert props[0]["extended"]["duels_won"] == pytest.approx(3.5)
    assert props[0]["extended"]["dribbles_success"] == pytest.approx(2.0)


def _rates_for(names):
    return [{
        "player": name, "minutes": 810, "expected_start_minutes": 81.0,
        "per90": {"g": 0.3, "a": 0.2, "r": 2.5, "rp": 1.0, "fc": 1.3, "fr": 1.1, "t": 0.2},
        "source": "API-Football · players",
    } for name in names]


class OfficialClient:
    offline = False

    def find_fixture(self, *_args):
        return {"fixture": {"id": 42}}

    def get_official_lineup(self, _fixture_id):
        positions = ["POR", "LI", "DFC", "DFC", "LD", "MC", "MCD", "MC", "EI", "DC", "ED"]
        return [
            {"team": "Local FC", "formation": "4-3-3", "starters": [{"name": f"Local {i}", "position": p} for i, p in enumerate(positions)]},
            {"team": "Visitante CF", "formation": "4-3-3", "starters": [{"name": f"Visitante {i}", "position": p} for i, p in enumerate(positions)]},
        ]

    def get_absences(self, _fixture_id):
        return []


def test_once_oficial_sustituye_estimacion_por_props_reales(monkeypatch):
    now = datetime(2026, 8, 24, 19, tzinfo=MADRID)
    match = {
        "id": "m1", "league": "LaLiga", "home": "Local FC", "away": "Visitante CF",
        "kickoff": (now + timedelta(hours=1)).isoformat(), "xg": [1.4, 1.0], "stats": {},
    }

    def fake_rates(_client, team, *_args, **_kwargs):
        prefix = "Local" if team == "Local FC" else "Visitante"
        return _rates_for([f"{prefix} {i}" for i in range(11)])

    monkeypatch.setattr("futbol_pred.operational.fetch_team_player_rates", fake_rates)
    assert attach_official_context([match], now, OfficialClient()) == 1
    lineup = match["alineacion"]
    assert lineup["status"] == "confirmado"
    assert lineup["player_props_source"].startswith("API-Football · players")
    assert lineup["numeric_props_source"] == "API-Football · players"
    assert lineup["quality"]["real_player_props"] == 22
    assert lineup["quality"]["props_players"] == 22
    assert len(lineup["clave_local"]) == 11
    assert len(lineup["clave_visitante"]) == 11
    assert [row["jugador"] for row in lineup["clave_local"]] == [f"Local {i}" for i in range(11)]
    assert [row["jugador"] for row in lineup["clave_visitante"]] == [f"Visitante {i}" for i in range(11)]
    assert all(row["source"] == "API-Football · players" for row in lineup["clave_local"] + lineup["clave_visitante"])
    assert all(row["tit"] == 1.0 for row in lineup["clave_local"] + lineup["clave_visitante"])


def test_once_oficial_sin_endpoint_degrada_sin_inventar_props(monkeypatch):
    now = datetime(2026, 8, 24, 19, tzinfo=MADRID)
    match = {
        "id": "m2", "league": "LaLiga", "home": "Local FC", "away": "Visitante CF",
        "kickoff": (now + timedelta(hours=1)).isoformat(), "xg": [1.2, 0.9], "stats": {},
    }
    monkeypatch.setattr("futbol_pred.operational.fetch_team_player_rates", lambda *_a, **_k: [])
    assert attach_official_context([match], now, OfficialClient()) == 1
    lineup = match["alineacion"]
    assert lineup["player_props_source"] == "sin datos reales suficientes"
    assert lineup["numeric_props_source"] == "pending_real_data"
    assert lineup["quality"]["real_player_props"] == 0
    assert lineup["quality"]["props_players"] == 0
    assert lineup["clave_local"] == []
    assert lineup["clave_visitante"] == []
