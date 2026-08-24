"""Previsión meteorológica gratuita y cacheable para la hora del partido."""

from __future__ import annotations

from datetime import datetime
import math

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _heat_context(temperature: float, apparent: float, humidity: float) -> dict:
    # Etiqueta operativa, no corrección de goles. El umbral usa temperatura
    # aparente y humedad para avisar de estrés térmico sin fingir un WBGT medido.
    load = max(temperature, apparent) + max(0.0, humidity - 60.0) * 0.04
    level = "alto" if load >= 32 else "moderado" if load >= 26 else "bajo"
    return {
        "level": level,
        "index": round(load, 1),
        "method": "temperatura aparente + humedad; no es WBGT",
    }


class WeatherClient:
    def __init__(self, timeout: int = 12, session=requests):
        self.timeout = timeout
        self.session = session

    def forecast(self, venue: dict, kickoff: datetime) -> dict | None:
        params = {
            "latitude": venue["latitude"],
            "longitude": venue["longitude"],
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,wind_speed_10m,weather_code",
            "timezone": "Europe/Madrid",
            "forecast_days": 16,
        }
        try:
            response = self.session.get(FORECAST_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            hourly = data.get("hourly") or {}
            times = [datetime.fromisoformat(value) for value in hourly.get("time") or []]
            target = kickoff.replace(tzinfo=None)
            index = min(range(len(times)), key=lambda idx: abs((times[idx] - target).total_seconds()))
            if abs((times[index] - target).total_seconds()) > 2 * 3600:
                return None
            def value(key, default=0.0):
                raw = (hourly.get(key) or [])[index]
                number = float(raw)
                return number if math.isfinite(number) else default
            temperature = value("temperature_2m")
            apparent = value("apparent_temperature", temperature)
            humidity = value("relative_humidity_2m")
            return {
                "forecast_for": times[index].isoformat(),
                "temperature_c": round(temperature, 1),
                "apparent_temperature_c": round(apparent, 1),
                "humidity_pct": round(humidity),
                "precipitation_probability_pct": round(value("precipitation_probability")),
                "wind_kmh": round(value("wind_speed_10m"), 1),
                "weather_code": round(value("weather_code")),
                "heat_stress": _heat_context(temperature, apparent, humidity),
                "source": "Open-Meteo",
                "source_url": "https://open-meteo.com/",
                "license": "CC BY 4.0",
                "model_use": "confianza_y_explicacion",
            }
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError):
            return None
