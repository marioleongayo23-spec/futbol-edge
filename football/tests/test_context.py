from datetime import datetime

from futbol_pred.context.venues import venue_for
from futbol_pred.context.weather import WeatherClient
from futbol_pred.ingest.api_football import ApiFootballClient
from futbol_pred.model.trends import TrendModel


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "hourly": {
                "time": ["2026-08-24T17:00", "2026-08-24T18:00"],
                "temperature_2m": [35.0, 33.0],
                "apparent_temperature": [38.0, 36.0],
                "relative_humidity_2m": [62, 64],
                "precipitation_probability": [5, 8],
                "wind_speed_10m": [9.2, 10.0],
                "weather_code": [1, 2],
            }
        }


class _Session:
    def get(self, *_args, **_kwargs):
        return _Response()


def test_registro_estadio_resuelve_alias_sin_acentos():
    venue = venue_for("Atlético Madrid")
    assert venue["name"] == "Riyadh Air Metropolitano"
    assert venue["source"].startswith("registro")
    assert venue_for("CA Osasuna")["name"] == "El Sadar"
    assert venue_for("Málaga CF")["name"] == "La Rosaleda"
    assert venue_for("Celta B")["name"] == "Abanca Balaídos"


def test_weather_elige_hora_y_etiqueta_calor_sin_modificar_modelo():
    weather = WeatherClient(session=_Session()).forecast(
        venue_for("Real Madrid"), datetime.fromisoformat("2026-08-24T17:30:00+02:00")
    )
    assert weather["temperature_c"] == 35.0
    assert weather["heat_stress"]["level"] == "alto"
    assert weather["model_use"] == "confianza_y_explicacion"


def test_matchup_tactico_declara_muestra_y_no_inventa_formacion():
    model = TrendModel()
    for _ in range(6):
        model._add("Local", "Visitante", "shots", 15, 8)
        model._add("Local", "Visitante", "fouls", 14, 15)
        model._add("Local", "Visitante", "yellows", 2, 3)
        model._add("Local", "Visitante", "corners", 7, 3)
        model._add("Local", "Visitante", "goals", 2, 1)
    profile = model.matchup_profile("Local", "Visitante")
    assert profile["reliability"] == "media"
    assert profile["minimum_samples"] == 6
    assert "no infiere una formación" in profile["method"]


def test_api_football_agrupa_ids_y_normaliza_contexto_avanzado(monkeypatch):
    client = ApiFootballClient(api_key="test")
    calls = []
    monkeypatch.setattr(client, "_get", lambda path, params: (
        calls.append((path, params)) or {"response": [{
            "fixture": {"id": 7, "referee": "A. Árbitro", "venue": {"name": "Estadio", "city": "Madrid"}},
            "statistics": [{"team": {"name": "Local"}, "statistics": [
                {"type": "Ball Possession", "value": "61%"}, {"type": "Total passes", "value": 520},
            ]}],
        }]}
    ))
    details = client.get_fixture_details([7, 7, 8])
    assert calls == [("fixtures", {"ids": "7-8"})]
    context = client.fixture_context(details[7])
    assert context["referee"] == "A. Árbitro"
    assert context["live_or_post_stats"]["Local"]["passes"] == 520
