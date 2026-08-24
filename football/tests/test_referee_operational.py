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
        out["fouls"] = {"home": 12.1, "away": 13.2, "total": 25.3}
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
