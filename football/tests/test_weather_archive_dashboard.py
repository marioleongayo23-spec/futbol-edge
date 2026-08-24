from datetime import datetime, timedelta

from futbol_pred.dashboard import MADRID, _attach_archived_weather
from futbol_pred.feed_quality import preserve_last_known_good


class _ArchiveClient:
    def __init__(self):
        self.calls = []

    def historical(self, venue, kickoff):
        self.calls.append((venue["name"], kickoff))
        return {
            "historical_for": kickoff.replace(tzinfo=None).isoformat(timespec="hours"),
            "temperature_c": 24.0,
            "precipitation_mm": 0.3,
            "wind_kmh": 12.0,
            "source": "Open-Meteo Historical Forecast",
            "model_use": "validacion_historica_sin_impacto_en_prediccion",
        }


def _finished(match_id, home, kickoff):
    return {
        "id": match_id,
        "date": kickoff.date().isoformat(),
        "home": home,
        "away": "Rival",
        "league": "LaLiga",
        "kickoff": kickoff.isoformat(),
        "status": "FINISHED",
        "finished": True,
    }


def test_archived_weather_solo_rellena_terminados_antiguos_y_respeta_limite():
    now = datetime(2026, 8, 24, 19, 0, tzinfo=MADRID)
    old_1 = _finished("m1", "Real Madrid", now - timedelta(days=3))
    old_2 = _finished("m2", "Atlético Madrid", now - timedelta(days=2))
    recent = _finished("m3", "Real Madrid", now - timedelta(hours=4))
    upcoming = {
        **_finished("m4", "Real Madrid", now + timedelta(days=1)),
        "finished": False,
        "status": "SCHEDULED",
    }
    client = _ArchiveClient()

    updated = _attach_archived_weather(
        [old_1, old_2, recent, upcoming], now, client=client, limit=1
    )

    assert updated == 1
    assert len(client.calls) == 1
    assert "weather_actual" in old_1
    assert "weather_actual" not in old_2
    assert "weather_actual" not in recent
    assert "weather_actual" not in upcoming
    assert old_1["weather_actual"]["source_updated_at"].startswith("2026-08-24T19:00")


def test_archived_weather_cacheado_no_se_vuelve_a_consultar():
    now = datetime(2026, 8, 24, 19, 0, tzinfo=MADRID)
    match = _finished("m1", "Real Madrid", now - timedelta(days=3))
    match["weather_actual"] = {"temperature_c": 22, "source": "cache"}
    client = _ArchiveClient()

    assert _attach_archived_weather([match], now, client=client, limit=6) == 0
    assert client.calls == []


def test_last_known_good_conserva_weather_actual_para_cache_persistente():
    now = datetime(2026, 8, 24, 19, 0, tzinfo=MADRID)
    old_match = _finished("m1", "Real Madrid", now - timedelta(days=3))
    old_match["weather_actual"] = {"temperature_c": 21.5, "source": "archivo"}
    new_match = _finished("m1", "Real Madrid", now - timedelta(days=3))

    candidate = {"schema_version": 7, "matches": [new_match]}
    previous = {"schema_version": 7, "matches": [old_match]}
    preserve_last_known_good(candidate, previous)

    assert candidate["matches"][0]["weather_actual"] == old_match["weather_actual"]
