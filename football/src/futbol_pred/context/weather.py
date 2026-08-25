"""Tiempo futuro e histórico gratuito para el estadio y la hora del partido.

El forecast futuro alimenta un ajuste contextual, conservador y explícito de xG,
remates y disciplina. El histórico queda separado como evidencia para validar o
recalibrar esos multiplicadores sin contaminar predicciones pasadas.
"""

from __future__ import annotations

from datetime import datetime
import math

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


def _heat_context(temperature: float, apparent: float, humidity: float) -> dict:
    load = max(temperature, apparent) + max(0.0, humidity - 60.0) * 0.04
    level = "alto" if load >= 32 else "moderado" if load >= 26 else "bajo"
    return {
        "level": level,
        "index": round(load, 1),
        "method": "temperatura aparente + humedad; no es WBGT",
    }


def _nearest_hour(hourly: dict, target: datetime, tolerance_hours: int = 2) -> tuple[int, list[datetime]] | None:
    times = [datetime.fromisoformat(value) for value in hourly.get("time") or []]
    if not times:
        return None
    naive_target = target.replace(tzinfo=None)
    index = min(range(len(times)), key=lambda idx: abs((times[idx] - naive_target).total_seconds()))
    if abs((times[index] - naive_target).total_seconds()) > tolerance_hours * 3600:
        return None
    return index, times


def _number_at(hourly: dict, key: str, index: int, default: float = 0.0) -> float:
    raw = (hourly.get(key) or [])[index]
    number = float(raw)
    return number if math.isfinite(number) else default


class WeatherClient:
    def __init__(self, timeout: int = 12, session=requests):
        self.timeout = timeout
        self.session = session

    def forecast(self, venue: dict, kickoff: datetime) -> dict | None:
        params = {
            "latitude": venue["latitude"],
            "longitude": venue["longitude"],
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,precipitation_probability,wind_speed_10m,weather_code",
            "timezone": "Europe/Madrid",
            "forecast_days": 16,
        }
        try:
            response = self.session.get(FORECAST_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            hourly = (response.json().get("hourly") or {})
            nearest = _nearest_hour(hourly, kickoff)
            if nearest is None:
                return None
            index, times = nearest
            temperature = _number_at(hourly, "temperature_2m", index)
            apparent = _number_at(hourly, "apparent_temperature", index, temperature)
            humidity = _number_at(hourly, "relative_humidity_2m", index)
            return {
                "forecast_for": times[index].isoformat(),
                "temperature_c": round(temperature, 1),
                "apparent_temperature_c": round(apparent, 1),
                "humidity_pct": round(humidity),
                "precipitation_mm": round(_number_at(hourly, "precipitation", index), 2),
                "precipitation_probability_pct": round(_number_at(hourly, "precipitation_probability", index)),
                "wind_kmh": round(_number_at(hourly, "wind_speed_10m", index), 1),
                "weather_code": round(_number_at(hourly, "weather_code", index)),
                "heat_stress": _heat_context(temperature, apparent, humidity),
                "source": "Open-Meteo",
                "source_url": "https://open-meteo.com/",
                "license": "CC BY 4.0",
                "model_use": "ajuste_cuantitativo_contextual",
            }
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError):
            return None

    def historical(self, venue: dict, kickoff: datetime) -> dict | None:
        """Devuelve condiciones pasadas horarias próximas al saque inicial.

        Usa Historical Forecast de Open-Meteo: una serie horaria construida con
        los primeros pasos de sucesivos modelos operativos. Sigue siendo dato
        modelizado, no estación; se mantiene como evidencia de validación.
        """

        day = kickoff.date().isoformat()
        params = {
            "latitude": venue["latitude"],
            "longitude": venue["longitude"],
            "start_date": day,
            "end_date": day,
            "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
            "timezone": "Europe/Madrid",
        }
        try:
            response = self.session.get(HISTORICAL_FORECAST_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            hourly = (response.json().get("hourly") or {})
            nearest = _nearest_hour(hourly, kickoff)
            if nearest is None:
                return None
            index, times = nearest
            temperature = _number_at(hourly, "temperature_2m", index)
            apparent = _number_at(hourly, "apparent_temperature", index, temperature)
            humidity = _number_at(hourly, "relative_humidity_2m", index)
            return {
                "historical_for": times[index].isoformat(),
                "temperature_c": round(temperature, 1),
                "apparent_temperature_c": round(apparent, 1),
                "humidity_pct": round(humidity),
                "precipitation_mm": round(_number_at(hourly, "precipitation", index), 2),
                "wind_kmh": round(_number_at(hourly, "wind_speed_10m", index), 1),
                "weather_code": round(_number_at(hourly, "weather_code", index)),
                "heat_stress": _heat_context(temperature, apparent, humidity),
                "source": "Open-Meteo Historical Forecast",
                "source_url": "https://open-meteo.com/en/docs/historical-forecast-api",
                "license": "CC BY 4.0",
                "data_type": "modelo_operativo_historico_horario",
                "model_use": "validacion_historica",
            }
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError):
            return None
