"""Tests del cliente OpenFootball (parser, sin red)."""

from futbol_pred.ingest.openfootball import OpenFootballClient, season_str


def test_season_str():
    assert season_str(2025) == "2025-26"
    assert season_str(2026) == "2026-27"


_FAKE = {
    "name": "Segunda División 2025/26",
    "matches": [
        {"round": "1. Round", "date": "2025-08-15", "time": "20:30",
         "team1": "Burgos CF", "team2": "Cultural Leonesa",
         "score": {"ft": [5, 1], "ht": [3, 0]}},
        {"round": "2. Round", "date": "2025-08-22",
         "team1": "Almería", "team2": "Málaga"},
    ],
}


def test_parse_partido_jugado_y_pendiente():
    fx = OpenFootballClient.parse(_FAKE, "segunda", 2025)
    assert len(fx) == 2

    jugado = fx[0]
    assert jugado.home_team == "Burgos CF" and jugado.away_team == "Cultural Leonesa"
    assert jugado.home_goals == 5 and jugado.away_goals == 1
    assert jugado.status == "FINISHED"
    assert jugado.matchday == 1
    assert jugado.source == "openfootball"

    pendiente = fx[1]
    assert pendiente.home_goals is None
    assert pendiente.status == "SCHEDULED"
    assert pendiente.matchday == 2


def test_kickoff_es_tz_aware():
    fx = OpenFootballClient.parse(_FAKE, "segunda", 2025)
    assert fx[0].kickoff.tzinfo is not None
