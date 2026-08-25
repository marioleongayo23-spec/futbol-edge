from datetime import datetime

from futbol_pred.context.venues import venue_for
from futbol_pred.context.weather import HISTORICAL_FORECAST_URL, WeatherClient


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "hourly": {
                "time": ["2026-08-18T20:00", "2026-08-18T21:00", "2026-08-18T22:00"],
                "temperature_2m": [31.0, 29.5, 28.0],
                "apparent_temperature": [33.0, 31.2, 29.4],
                "relative_humidity_2m": [54, 59, 63],
                "precipitation": [0.0, 1.7, 0.4],
                "wind_speed_10m": [8.0, 13.4, 11.0],
                "weather_code": [1, 61, 3],
            }
        }


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


def test_historical_weather_usa_hora_mas_cercana_y_precipitacion_real_modelizada():
    session = _Session()
    weather = WeatherClient(session=session).historical(
        venue_for("Real Madrid"),
        datetime.fromisoformat("2026-08-18T21:20:00+02:00"),
    )

    assert weather["historical_for"] == "2026-08-18T21:00:00"
    assert weather["temperature_c"] == 29.5
    assert weather["precipitation_mm"] == 1.7
    assert weather["wind_kmh"] == 13.4
    assert "precipitation_probability_pct" not in weather
    assert weather["source"] == "Open-Meteo Historical Forecast"
    assert weather["data_type"] == "modelo_operativo_historico_horario"
    assert weather["model_use"] == "validacion_historica_sin_impacto_en_prediccion"

    url, kwargs = session.calls[0]
    assert url == HISTORICAL_FORECAST_URL
    assert kwargs["params"]["start_date"] == "2026-08-18"
    assert kwargs["params"]["end_date"] == "2026-08-18"
    assert kwargs["params"]["timezone"] == "Europe/Madrid"


def test_historical_weather_no_inventa_si_no_hay_horas():
    class EmptyResponse(_Response):
        def json(self):
            return {"hourly": {"time": []}}

    class EmptySession:
        def get(self, *_args, **_kwargs):
            return EmptyResponse()

    result = WeatherClient(session=EmptySession()).historical(
        venue_for("Real Madrid"),
        datetime.fromisoformat("2026-08-18T21:00:00+02:00"),
    )
    assert result is None
