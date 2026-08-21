"""Test del cliente football-data.org con respuesta simulada (sin red)."""

import pytest

from futbol_pred.ingest import football_data
from futbol_pred.ingest.football_data import FootballDataClient


_FAKE_RESPONSE = {
    "matches": [
        {
            "id": 12345,
            "utcDate": "2025-08-20T19:00:00Z",
            "status": "FINISHED",
            "matchday": 1,
            "stage": "REGULAR_SEASON",
            "homeTeam": {"name": "Girona FC"},
            "awayTeam": {"name": "Rayo Vallecano de Madrid"},
            "score": {"fullTime": {"home": 1, "away": 3}},
        },
        {
            "id": 12346,
            "utcDate": "2025-08-21T19:00:00Z",
            "status": "SCHEDULED",
            "matchday": 1,
            "stage": "REGULAR_SEASON",
            "homeTeam": {"name": "FC Barcelona"},
            "awayTeam": {"name": "Valencia CF"},
            "score": {"fullTime": {"home": None, "away": None}},
        },
    ]
}


class _FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_parse_de_respuesta_football_data(monkeypatch):
    def fake_get(url, headers, params, timeout):
        assert headers["X-Auth-Token"] == "clave-de-prueba"
        assert "competitions/PD/matches" in url
        return _FakeResp(_FAKE_RESPONSE)

    monkeypatch.setattr(football_data.requests, "get", fake_get)
    client = FootballDataClient(api_key="clave-de-prueba")
    assert not client.offline

    fixtures = client.get_matches("laliga", season=2025)
    assert len(fixtures) == 2

    jugado = fixtures[0]
    assert jugado.home_team == "Girona FC"
    assert jugado.home_goals == 1 and jugado.away_goals == 3
    assert jugado.matchday == 1
    assert jugado.stage == "REGULAR_SEASON"
    assert jugado.source == "football_data"

    programado = fixtures[1]
    assert programado.home_goals is None
    assert programado.status == "SCHEDULED"


def test_offline_sin_clave_no_rompe(monkeypatch):
    # Sin clave usa datos de ejemplo (no toca la red).
    client = FootballDataClient(api_key=None)
    assert client.offline
    fixtures = client.get_matches("laliga", season=2025)
    assert len(fixtures) > 0


def test_nombres_cruzables_con_normalize():
    # Los nombres de football-data deben resolver a canónico (integración).
    from futbol_pred.normalize import canonical_team

    assert canonical_team("Girona FC") == "Girona"
    assert canonical_team("Rayo Vallecano de Madrid") == "Vallecano"
