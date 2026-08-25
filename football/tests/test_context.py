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
                "precipitation": [0.0, 0.3],
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


def test_registro_cubre_nombres_oficiales_largos_del_feed():
    expected = {
        "Deportivo Alavés": "Mendizorrotza",
        "RCD Espanyol de Barcelona": "RCDE Stadium",
        "Rayo Vallecano de Madrid": "Vallecas",
        "Real Betis Balompié": "Benito Villamarín",
        "Real Racing Club de Santander": "El Sardinero",
        "Real Sociedad de Fútbol": "Reale Arena",
    }
    assert {team: venue_for(team)["name"] for team in expected} == expected


def test_weather_elige_hora_y_expone_inputs_para_ajuste_cuantificado():
    weather = WeatherClient(session=_Session()).forecast(
        venue_for("Real Madrid"), datetime.fromisoformat("2026-08-24T17:30:00+02:00")
    )
    assert weather["temperature_c"] == 35.0
    assert weather["precipitation_mm"] == 0.0
    assert weather["heat_stress"]["level"] == "alto"
    assert weather["model_use"] == "ajuste_cuantitativo_contextual"


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
    assert set(profile["home"]["style_vector"]) == {
        "attack_volume", "territorial_pressure", "defensive_exposure",
        "finishing_efficiency", "contact_intensity",
    }
    assert all(
        dimension["score"] is None or 0 <= dimension["score"] <= 100
        for dimension in profile["home"]["style_vector"].values()
    )


def test_matchup_tactico_detecta_choque_de_volumen_y_exposicion():
    model = TrendModel()
    for _ in range(8):
        model._add("Dominante", "Fragil", "shots", 20, 7)
        model._add("Dominante", "Fragil", "corners", 9, 2)
        model._add("Dominante", "Fragil", "goals", 2, 1)
        model._add("Dominante", "Fragil", "fouls", 12, 10)
        model._add("Dominante", "Fragil", "yellows", 2, 2)
        model._add("Control", "Solido", "shots", 9, 8)
        model._add("Control", "Solido", "corners", 3, 3)
        model._add("Control", "Solido", "goals", 1, 1)
        model._add("Control", "Solido", "fouls", 10, 9)
        model._add("Control", "Solido", "yellows", 1, 1)
    profile = model.matchup_profile("Dominante", "Fragil")
    assert profile["home"]["style_vector"]["attack_volume"]["score"] >= 65
    assert profile["away"]["style_vector"]["defensive_exposure"]["score"] >= 65
    assert profile["style_clashes"][0]["edge"] == "home_attack"


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


def test_api_football_parsea_onces_agrupados_con_posicion_original():
    positions = [
        ("1:1", "G"), ("2:1", "D"), ("2:2", "D"), ("2:3", "D"), ("2:4", "D"),
        ("3:1", "M"), ("3:2", "M"), ("3:4", "M"),
        ("4:1", "F"), ("5:2", "F"), ("4:4", "F"),
    ]
    response = []
    for team in ("Local FC", "Visitante CF"):
        response.append({
            "team": {"name": team},
            "formation": "4-3-3",
            "coach": {"name": f"Entrenador {team}"},
            "startXI": [
                {"player": {"name": f"{team} {index}", "grid": grid, "pos": raw}}
                for index, (grid, raw) in enumerate(positions)
            ],
        })

    parsed = ApiFootballClient._parse_lineups(response)

    assert len(parsed) == 2
    assert all(len(team["starters"]) == 11 for team in parsed)
    assert parsed[0]["formation"] == "4-3-3"
    assert [row["position"] for row in parsed[0]["starters"]] == [
        "POR", "LI", "DFC", "DFC", "LD", "MI", "MCD", "MD", "EI", "DC", "ED",
    ]
