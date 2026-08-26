from datetime import datetime

from futbol_pred.hot_refresh import refresh_payload


class _Weather:
    def forecast(self, _venue, _kickoff):
        return {
            "forecast_for": "2026-08-26T20:00:00",
            "temperature_c": 29.0,
            "apparent_temperature_c": 30.0,
            "humidity_pct": 55,
            "precipitation_mm": 0.0,
            "precipitation_probability_pct": 10,
            "wind_kmh": 12.0,
            "weather_code": 1,
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/",
            "license": "CC BY 4.0",
            "model_use": "ajuste_cuantitativo_contextual",
        }


class _Football:
    offline = False

    def __init__(self, status="NS", goals=None, absences=None):
        self.status = status
        self.goals = goals or {"home": None, "away": None}
        self.absences = absences

    def find_fixture(self, _home, _away, _kickoff):
        return {
            "fixture": {"id": 77, "status": {"short": self.status}},
            "goals": self.goals,
        }

    def get_absences(self, _fixture_id):
        if self.absences is not None:
            return self.absences
        return [{
            "jugador": "Lesionado Real",
            "team": "Real Madrid",
            "estado": "injury",
            "detalle": "Hamstring Injury",
            "source": "API-Football",
            "official": True,
        }]

    def get_official_lineup(self, _fixture_id):
        def side(team, prefix):
            return {
                "team": team,
                "formation": "4-3-3",
                "starters": [
                    {"name": f"{prefix} {i}", "position": "POR" if i == 0 else "DFC" if i < 5 else "MC" if i < 8 else "DC"}
                    for i in range(11)
                ],
            }
        return [side("Real Madrid", "RM"), side("Real Betis", "BET")]


def _feed(kickoff="2026-08-26T20:00:00+02:00"):
    match = {
        "id": "m-1",
        "home": "Real Madrid",
        "away": "Real Betis",
        "league": "LaLiga",
        "date": "2026-08-26",
        "kickoff": kickoff,
        "status": "SCHEDULED",
        "finished": False,
        "engine": "dixon-coles",
        "probs": [60, 23, 17],
        "xg": [1.8, 0.8],
        "markets": {"marcador": "2-0"},
        "alineacion": {
            "local": [f"Plantilla RM {i}" for i in range(11)],
            "visitante": [f"Plantilla BET {i}" for i in range(11)],
            "posiciones_local": ["MC"] * 11,
            "posiciones_visitante": ["MC"] * 11,
            "formacion_local": "4-3-3",
            "formacion_visitante": "4-3-3",
            "status": "estimado",
            "provider": "Motor estadístico local",
            "model": "squad-only-v3",
            "clave_local": [],
            "clave_visitante": [],
        },
    }
    return {
        "schema_version": 7,
        "generated_at": "2026-08-26T18:00:00+02:00",
        "season": 2026,
        "counts": {"total": 20, "jugados": 0, "proximos": 20, "con_prediccion": 1},
        "matches": [match] + [
            {
                "id": f"future-{i}", "home": f"Home {i}", "away": f"Away {i}",
                "league": "LaLiga", "date": "2026-08-27",
                "kickoff": "2026-08-27T20:00:00+02:00", "status": "SCHEDULED",
                "finished": False,
            }
            for i in range(19)
        ],
    }


def test_hot_refresh_actualiza_clima_bajas_y_once_oficial_en_t60():
    feed = _feed()
    changed, stats = refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=_Weather(),
        football_client=_Football(),
    )

    match = feed["matches"][0]
    assert changed is True
    assert stats == {"weather": 1, "fixture": 1, "lineup": 1, "absences": 1}
    assert match["weather"]["temperature_c"] == 29.0
    assert match["alineacion"]["status"] == "confirmado"
    assert match["alineacion"]["provider"] == "API-Football"
    assert match["alineacion"]["local"][0] == "RM 0"
    assert match["alineacion"]["disponibilidad_local"][0]["jugador"] == "Lesionado Real"
    checks = match["operational_checks"]
    assert checks["weather_checked_at"] == "2026-08-26T19:00:00+02:00"
    assert checks["fixture_checked_at"] == "2026-08-26T19:00:00+02:00"
    assert checks["absences_checked_at"] == "2026-08-26T19:00:00+02:00"
    assert checks["lineup_checked_at"] == "2026-08-26T19:00:00+02:00"
    assert checks["lineup_check_result"] == "published"
    assert feed["generated_at"] == "2026-08-26T19:00:00+02:00"


def test_hot_refresh_registra_comprobacion_aunque_el_dato_no_cambie():
    feed = _feed()
    refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=_Weather(),
        football_client=_Football(),
    )
    first_lineup_check = feed["matches"][0]["operational_checks"]["lineup_checked_at"]

    changed, stats = refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:10:00+02:00"),
        weather_client=_Weather(),
        football_client=_Football(),
    )

    match = feed["matches"][0]
    checks = match["operational_checks"]
    assert changed is True
    assert stats == {"weather": 0, "fixture": 0, "lineup": 0, "absences": 0}
    assert checks["weather_checked_at"] == "2026-08-26T19:10:00+02:00"
    assert checks["fixture_checked_at"] == "2026-08-26T19:10:00+02:00"
    # En T-50 la alineación ya estaba confirmada: no se llama otra vez al endpoint.
    assert checks["lineup_checked_at"] == first_lineup_check
    assert feed["generated_at"] == "2026-08-26T19:10:00+02:00"


def test_hot_refresh_limpia_baja_antigua_si_la_fuente_ya_no_la_reporta():
    feed = _feed()
    match = feed["matches"][0]
    match["alineacion"]["disponibilidad_local"] = [{
        "jugador": "Ya Recuperado",
        "team": "Real Madrid",
        "estado": "injury",
        "detalle": "Old injury",
        "source": "API-Football",
    }]
    match["alineacion"]["bajas_local"] = ["Ya Recuperado (Old injury)"]

    changed, stats = refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=_Weather(),
        football_client=_Football(absences=[]),
    )

    assert changed is True
    assert stats["absences"] == 1
    assert match["alineacion"]["disponibilidad_local"] == []
    assert match["alineacion"]["bajas_local"] == []
    assert match["operational_checks"]["absences_check_result"] == "ok"


def test_hot_refresh_cierra_resultado_sin_reentrenar_modelo():
    feed = _feed(kickoff="2026-08-26T18:00:00+02:00")
    football = _Football(status="FT", goals={"home": 2, "away": 1})
    changed, stats = refresh_payload(
        feed,
        now=datetime.fromisoformat("2026-08-26T19:00:00+02:00"),
        weather_client=_Weather(),
        football_client=football,
    )

    match = feed["matches"][0]
    assert changed is True
    assert stats["fixture"] == 1
    assert match["finished"] is True
    assert match["result"] == [2, 1]
    assert match["engine"] == "resultado-real"
    assert match["operational_checks"]["fixture_checked_at"] == "2026-08-26T19:00:00+02:00"
    assert feed["counts"]["jugados"] == 1
    assert feed["counts"]["proximos"] == 19
