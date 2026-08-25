from copy import deepcopy
from datetime import datetime, timezone

from futbol_pred.weather_effects import apply_weather_adjustment, weather_multipliers


def test_viento_y_lluvia_reducen_goles_y_suben_contacto():
    mult = weather_multipliers({"wind_kmh": 38, "precipitation_mm": 5, "apparent_temperature_c": 22})
    assert mult["goals"] < 1
    assert mult["shots"] < 1
    assert mult["fouls"] > 1
    assert mult["cards"] > 1
    assert mult["reasons"]


def test_ajuste_modifica_xg_stats_mercados_y_value_sin_tocar_1x2():
    match = {
        "finished": False,
        "xg": [1.8, 1.1],
        "probs": [52, 27, 21],
        "markets": {"over_2_5": 0.55, "btts": 0.50},
        "value": [
            {"market": "1x2", "selection": "1", "odds": 2.0, "modelProb": .52, "edge": .04},
            {"market": "ou25", "selection": "over", "odds": 2.1, "modelProb": .55, "edge": .155},
            {"market": "ou25", "selection": "under", "odds": 1.8, "modelProb": .45, "edge": -.19},
        ],
        "stats": {
            "goals": {"home": 1.8, "away": 1.1, "total": 2.9},
            "shots": {"home": 14, "away": 10, "total": 24},
            "sot": {"home": 5, "away": 4, "total": 9},
            "fouls": {"home": 12, "away": 13, "total": 25},
            "yellows": {"home": 2.0, "away": 2.4, "total": 4.4},
        },
        "weather": {
            "source_updated_at": "2026-08-25T10:15:00+02:00",
            "wind_kmh": 31,
            "precipitation_mm": 2.5,
            "precipitation_probability_pct": 90,
            "apparent_temperature_c": 24,
        },
    }
    before_probs = list(match["probs"])
    before_1x2 = dict(match["value"][0])
    old_over_prob = match["value"][1]["modelProb"]
    assert apply_weather_adjustment(match, datetime(2026, 8, 25, 10, 16, tzinfo=timezone.utc))
    assert match["xg"][0] < 1.8 and match["xg"][1] < 1.1
    assert match["stats"]["shots"]["total"] < 24
    assert match["stats"]["fouls"]["total"] > 25
    assert match["stats"]["yellows"]["total"] > 4.4
    assert match["probs"] == before_probs
    assert match["value"][0] == before_1x2
    assert match["value"][1]["modelProb"] == match["markets"]["over_2_5"]
    assert match["value"][1]["modelProb"] != old_over_prob
    assert match["value"][1]["weather_adjusted"] is True
    assert match["value"][1]["edge"] == round(match["value"][1]["modelProb"] * 2.1 - 1, 3)
    assert match["weather_adjustment"]["one_x_two_adjusted"] is False
    assert match["weather_adjustment"]["xg"]["delta"][0] < 0


def test_mismo_forecast_no_se_aplica_dos_veces_sobre_el_mismo_xg():
    match = {
        "finished": False,
        "xg": [1.5, 1.0],
        "stats": {},
        "markets": {},
        "weather": {"source_updated_at": "stamp", "wind_kmh": 30},
    }
    assert apply_weather_adjustment(match)
    xg = list(match["xg"])
    assert apply_weather_adjustment(match) is False
    assert match["xg"] == xg


def test_mismo_forecast_se_reaplica_si_el_cron_reconstruye_xg_base():
    match = {
        "finished": False,
        "xg": [1.5, 1.0],
        "stats": {"shots": {"home": 12, "away": 8, "total": 20}},
        "markets": {},
        "weather": {"source_updated_at": "stamp", "wind_kmh": 30},
    }
    assert apply_weather_adjustment(match)
    published_adjustment = deepcopy(match["weather_adjustment"])
    published_after = list(match["xg"])

    # Simula el siguiente cron: el modelo vuelve a crear xG/stats base, mientras
    # preserve_last_known_good recupera la metadata del ajuste anterior.
    rebuilt = {
        "finished": False,
        "xg": [1.5, 1.0],
        "stats": {"shots": {"home": 12, "away": 8, "total": 20}},
        "markets": {},
        "weather": {"source_updated_at": "stamp", "wind_kmh": 30},
        "weather_adjustment": published_adjustment,
    }
    assert apply_weather_adjustment(rebuilt) is True
    assert rebuilt["xg"] == published_after
    assert rebuilt["weather_adjustment"]["xg"]["before"] == [1.5, 1.0]


def test_clima_neutro_no_altera_prediccion():
    match = {
        "finished": False,
        "xg": [1.5, 1.0],
        "stats": {"shots": {"home": 10, "away": 8, "total": 18}},
        "markets": {"over_2_5": 0.5},
        "weather": {"source_updated_at": "stamp", "wind_kmh": 10, "precipitation_mm": 0, "apparent_temperature_c": 20},
    }
    assert apply_weather_adjustment(match) is False
    assert match["xg"] == [1.5, 1.0]
    assert match["weather_adjustment"]["applied"] is False
