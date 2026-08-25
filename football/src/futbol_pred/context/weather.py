"""Tiempo futuro e histórico gratuito para el estadio y la hora del partido.

El forecast futuro alimenta contexto de partido. Para validación se distinguen
explícitamente dos históricos:

* ``historical``: Historical Forecast, útil como aproximación de las condiciones
  finalmente observadas/modelizadas, pero demasiado cercano al evento para
  entrenar una decisión prepartido.
* ``previous_run``: Previous Model Runs a lead time fijo (por defecto T-24 h),
  que reproduce lo que el modelo meteorológico pronosticaba antes del partido y
  es el único histórico apto para el gate anti-leakage del ajuste cuantitativo.
"""

from __future__ import annotations

from datetime import datetime
import math

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
)


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
    values = hourly.get(key) or []
    if index >= len(values):
        return default
    raw = values[index]
    number = float(raw)
    return number if math.isfinite(number) else default


def _weather_payload(hourly: dict, index: int, times: list[datetime], *, suffix: str = "") -> dict:
    def key(name: str) -> str:
        return f"{name}{suffix}"

    temperature = _number_at(hourly, key("temperature_2m"), index)
    apparent = _number_at(hourly, key("apparent_temperature"), index, temperature)
    humidity = _number_at(hourly, key("relative_humidity_2m"), index)
    return {
        "forecast_for": times[index].isoformat(),
        "temperature_c": round(temperature, 1),
        "apparent_temperature_c": round(apparent, 1),
        "humidity_pct": round(humidity),
        "precipitation_mm": round(_number_at(hourly, key("precipitation"), index), 2),
        "wind_kmh": round(_number_at(hourly, key("wind_speed_10m"), index), 1),
        "weather_code": round(_number_at(hourly, key("weather_code"), index)),
        "heat_stress": _heat_context(temperature, apparent, humidity),
    }


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
            hourly = response.json().get("hourly") or {}
            nearest = _nearest_hour(hourly, kickoff)
            if nearest is None:
                return None
            index, times = nearest
            payload = _weather_payload(hourly, index, times)
            payload["precipitation_probability_pct"] = round(
                _number_at(hourly, "precipitation_probability", index)
            )
            payload.update({
                "source": "Open-Meteo",
                "source_url": "https://open-meteo.com/",
                "license": "CC BY 4.0",
                "model_use": "contexto_prepartido; ajuste solo si weather gate aceptado",
            })
            return payload
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError):
            return None

    def historical(self, venue: dict, kickoff: datetime) -> dict | None:
        """Condiciones pasadas cercanas al evento para contraste, no para gate.

        Historical Forecast concatena los primeros pasos de modelos operativos y
        por ello se aproxima mucho al tiempo finalmente ocurrido. No debe usarse
        como si hubiese sido un forecast T-24 conocido antes del partido.
        """

        day = kickoff.date().isoformat()
        params = {
            "latitude": venue["latitude"],
            "longitude": venue["longitude"],
            "start_date": day,
            "end_date": day,
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": "Europe/Madrid",
        }
        try:
            response = self.session.get(HISTORICAL_FORECAST_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            hourly = response.json().get("hourly") or {}
            nearest = _nearest_hour(hourly, kickoff)
            if nearest is None:
                return None
            index, times = nearest
            payload = _weather_payload(hourly, index, times)
            payload["historical_for"] = payload.pop("forecast_for")
            payload.update({
                "source": "Open-Meteo Historical Forecast",
                "source_url": "https://open-meteo.com/en/docs/historical-forecast-api",
                "license": "CC BY 4.0",
                "data_type": "modelo_operativo_historico_horario_cercano_al_evento",
                "model_use": "contraste_postpartido; prohibido_para_gate_prepartido",
            })
            return payload
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError):
            return None

    def previous_run(self, venue: dict, kickoff: datetime, lead_days: int = 1) -> dict | None:
        """Forecast histórico a lead time fijo, apto para validación prepartido.

        ``lead_days=1`` solicita las variables ``*_previous_day1`` que Open-Meteo
        define como el valor pronosticado 24 horas antes del instante válido.
        Solo se admiten 1..7 días para mantener el contrato del Previous Runs API.
        """

        if not 1 <= int(lead_days) <= 7:
            raise ValueError("lead_days debe estar entre 1 y 7")
        lead_days = int(lead_days)
        suffix = f"_previous_day{lead_days}"
        variables = [f"{name}{suffix}" for name in HOURLY_VARIABLES]
        day = kickoff.date().isoformat()
        params = {
            "latitude": venue["latitude"],
            "longitude": venue["longitude"],
            "start_date": day,
            "end_date": day,
            "hourly": ",".join(variables),
            "timezone": "Europe/Madrid",
        }
        try:
            response = self.session.get(PREVIOUS_RUNS_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            hourly = response.json().get("hourly") or {}
            nearest = _nearest_hour(hourly, kickoff)
            if nearest is None:
                return None
            index, times = nearest
            payload = _weather_payload(hourly, index, times, suffix=suffix)
            payload.update({
                "lead_hours": lead_days * 24,
                "forecast_issued_relative_to_valid_time": f"T-{lead_days * 24}h",
                "source": "Open-Meteo Previous Model Runs",
                "source_url": "https://open-meteo.com/en/docs/previous-runs-api",
                "license": "CC BY 4.0",
                "data_type": "forecast_historico_lead_fijo",
                "model_use": "weather_gate_prepartido",
                "leakage_safe": True,
            })
            return payload
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError):
            return None
