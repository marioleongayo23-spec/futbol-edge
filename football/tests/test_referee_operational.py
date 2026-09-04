from datetime import datetime
from zoneinfo import ZoneInfo

from futbol_pred.operational import attach_official_context

MADRID = ZoneInfo("Europe/Madrid")


class FakeClient:
    offline = False

    def find_fixture(self, home, away, kickoff):
        return {"fixture": {"id": 99, "referee": "Javier Alberola Rojas, Spain"}}

    def get_fixture_details(self, fixture_ids):
        assert fixture_ids == [99]
        return {
            99: {
                "fixture": {
                    "id": 99,
                    "referee": "Javier Alberola Rojas, Spain",
                    "venue": {"name": "Metropolitano", "city": "Madrid"},
                },
                "lineups": [],
            }
        }

    def lineup_from_fixture(self, detail):
        return []

    def get_official_lineup(self, fixture_id):
        return []

    def get_absences(self, fixture_id):
        return []

    def fixture_context(self, detail):
        fixture = detail["fixture"]
        return {
            "provider": "API-Football",
            "referee": fixture["referee"],
            "venue": fixture["venue"]["name"],
            "city": fixture["venue"]["city"],
        }


class FakeRefereeModel:
    def context(self, referee):
        assert "Alberola" in referee
        return {
            "method": "shrunk-referee-total-holdout",
            "accepted_stats": ["fouls"],
            "metrics": {"fouls": {"factor": 1.1, "n": 20, "accepted": True}},
        }

    def adjust_stats(self, stats, referee):
        out = {key: dict(value) for key, value in stats.items()}
        home = round(float(out["fouls"]["home"]) * 1.1, 2)
        away = round(float(out["fouls"]["away"]) * 1.1, 2)
        out["fouls"] = {"home": home, "away": away, "total": round(home + away, 2)}
        return out, ["fouls"]


class FakeStatsPredictor:
    referee_model = FakeRefereeModel()


def test_contexto_oficial_aplica_arbitro_solo_mediante_modelo_validado():
    now = datetime(2026, 8, 24, 20, 0, tzinfo=MADRID)
    match = {
        "home": "Atletico Madrid",
        "away": "Valencia",
        "league": "LaLiga",
        "kickoff": datetime(2026, 8, 24, 21, 0, tzinfo=MADRID).isoformat(),
        "stats": {
            "fouls": {"home": 11.0, "away": 12.0, "total": 23.0},
            "corners": {"home": 6.0, "away": 4.0, "total": 10.0},
        },
    }

    updated = attach_official_context(
        [match],
        now,
        client=FakeClient(),
        stats_models={"LaLiga": FakeStatsPredictor()},
    )

    # No hay once oficial, por lo que el contador de actualizaciones de alineación
    # sigue a cero; el contexto arbitral sí debe haberse enriquecido.
    assert updated == 0
    assert match["official_context"]["referee_profile"]["accepted_stats"] == ["fouls"]
    assert match["official_context"]["referee_adjustment_applied"] == ["fouls"]
    assert match["stats"]["fouls"]["total"] == 25.3
    assert match["stats"]["corners"]["total"] == 10.0


def test_contexto_oficial_no_aplica_dos_veces_el_mismo_factor():
    now = datetime(2026, 8, 24, 20, 0, tzinfo=MADRID)
    match = {
        "home": "Atletico Madrid",
        "away": "Valencia",
        "league": "LaLiga",
        "kickoff": datetime(2026, 8, 24, 21, 0, tzinfo=MADRID).isoformat(),
        # football-data.org ya aplicó x1.1 sobre la base 11/12.
        "stats": {"fouls": {"home": 12.1, "away": 13.2, "total": 25.3}},
        "official_context": {
            "referee": "Javier Alberola Rojas",
            "provider": "football-data.org",
            "referee_adjustment_applied": ["fouls"],
            "referee_profile": {
                "metrics": {"fouls": {"factor": 1.1, "accepted": True}}
            },
        },
    }

    attach_official_context(
        [match],
        now,
        client=FakeClient(),
        stats_models={"LaLiga": FakeStatsPredictor()},
    )

    # API-Football confirma el árbitro: se deshace el primer x1.1 y se aplica
    # una sola vez desde la base. Nunca debe acabar en 27.83 (x1.1 al cuadrado).
    assert match["stats"]["fouls"] == {"home": 12.1, "away": 13.2, "total": 25.3}
    assert match["official_context"]["provider"] == "API-Football"


class FakeClientSinArbitro(FakeClient):
    """API-Football responde el fixture pero SIN árbitro (típico pre-partido)."""

    def get_fixture_details(self, fixture_ids):
        return {99: {"fixture": {"id": 99, "referee": None,
                                 "venue": {"name": "San Mamés", "city": "Bilbao"}},
                     "lineups": []}}

    def fixture_context(self, detail):
        v = detail["fixture"]["venue"]
        return {"provider": "API-Football", "referee": None,
                "venue": v["name"], "city": v["city"]}


def test_contexto_oficial_no_borra_arbitro_rfef_si_api_no_lo_trae():
    # La designación RFEF ya encendió el árbitro en el build; una pasada posterior
    # de API-Football sin árbitro NO debe borrarlo (regresión del scraper RFEF).
    now = datetime(2026, 8, 24, 20, 0, tzinfo=MADRID)
    match = {
        "home": "Atletico Madrid", "away": "Valencia", "league": "LaLiga",
        "kickoff": datetime(2026, 8, 24, 21, 0, tzinfo=MADRID).isoformat(),
        "stats": {"fouls": {"home": 12.1, "away": 13.2, "total": 25.3}},
        "official_context": {
            "referee": "Gil Manzano", "provider": "RFEF", "source": "RFEF",
            "referee_adjustment_applied": ["fouls"],
            "referee_profile": {"metrics": {"fouls": {"factor": 1.1, "accepted": True}}},
        },
    }

    attach_official_context([match], now, client=FakeClientSinArbitro(),
                            stats_models={"LaLiga": FakeStatsPredictor()})

    oc = match["official_context"]
    assert oc["referee"] == "Gil Manzano"            # se conserva
    assert oc["provider"] == "RFEF"                   # procedencia real intacta
    assert oc["referee_adjustment_applied"] == ["fouls"]
    assert oc["referee_profile"]["metrics"]["fouls"]["accepted"] is True
    assert oc["venue"] == "San Mamés"                 # sí se enriquece la sede
