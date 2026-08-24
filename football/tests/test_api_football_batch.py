from futbol_pred.ingest.api_football import ApiFootballClient


class RecordingClient(ApiFootballClient):
    def __init__(self):
        super().__init__(api_key="test")
        self.calls = []

    def _get(self, path, params):
        self.calls.append((path, dict(params)))
        ids = [int(value) for value in str(params.get("ids") or "").split("-") if value]
        return {
            "response": [
                {
                    "fixture": {"id": fixture_id, "referee": f"Ref {fixture_id}", "venue": {"name": "Estadio", "city": "Madrid"}},
                    "statistics": [],
                }
                for fixture_id in ids
            ]
        }


def test_get_fixture_details_agrupa_todos_los_ids_en_chunks_de_20():
    client = RecordingClient()
    fixture_ids = list(range(1, 46)) + [1, 2]

    details = client.get_fixture_details(fixture_ids)

    assert set(details) == set(range(1, 46))
    assert len(client.calls) == 3
    assert [len(call[1]["ids"].split("-")) for call in client.calls] == [20, 20, 5]
    assert all(path == "fixtures" for path, _ in client.calls)


def test_get_fixture_details_falla_por_chunk_sin_perder_los_anteriores():
    class PartialClient(RecordingClient):
        def _get(self, path, params):
            ids = [int(value) for value in params["ids"].split("-")]
            self.calls.append((path, dict(params)))
            if ids[0] == 21:
                raise RuntimeError("quota")
            return {"response": [{"fixture": {"id": value}} for value in ids]}

    client = PartialClient()
    details = client.get_fixture_details(list(range(1, 46)))

    assert set(details) == set(range(1, 21)) | set(range(41, 46))
    assert len(client.calls) == 3


def test_fixture_context_normaliza_arbitro_y_estadisticas_clave_del_batch():
    item = {
        "fixture": {
            "id": 42,
            "referee": "Javier Alberola Rojas, Spain",
            "venue": {"name": "Metropolitano", "city": "Madrid"},
        },
        "statistics": [
            {
                "team": {"name": "Atletico Madrid"},
                "statistics": [
                    {"type": "Total Shots", "value": 16},
                    {"type": "Shots on Goal", "value": 7},
                    {"type": "Corner Kicks", "value": 8},
                    {"type": "Fouls", "value": 11},
                    {"type": "Yellow Cards", "value": 2},
                    {"type": "Red Cards", "value": 0},
                    {"type": "Ball Possession", "value": "58%"},
                    {"type": "Total passes", "value": 512},
                ],
            },
            {
                "team": {"name": "Valencia"},
                "statistics": [
                    {"type": "Total Shots", "value": 9},
                    {"type": "Shots on Goal", "value": 3},
                    {"type": "Corner Kicks", "value": 4},
                    {"type": "Fouls", "value": 15},
                    {"type": "Yellow Cards", "value": 4},
                    {"type": "Red Cards", "value": 1},
                    {"type": "Ball Possession", "value": "42%"},
                ],
            },
        ],
    }

    context = ApiFootballClient.fixture_context(item)

    assert context["referee"] == "Javier Alberola Rojas, Spain"
    assert context["venue"] == "Metropolitano"
    assert context["city"] == "Madrid"
    home = context["live_or_post_stats"]["Atletico Madrid"]
    away = context["live_or_post_stats"]["Valencia"]
    assert home == {
        "shots": 16,
        "sot": 7,
        "corners": 8,
        "fouls": 11,
        "yellows": 2,
        "reds": 0,
        "possession": 58.0,
        "passes": 512,
    }
    assert away["shots"] == 9
    assert away["sot"] == 3
    assert away["corners"] == 4
    assert away["fouls"] == 15
    assert away["yellows"] == 4
    assert away["reds"] == 1
    assert away["possession"] == 42.0
