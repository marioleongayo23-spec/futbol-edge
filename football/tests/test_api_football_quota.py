from futbol_pred.ingest.api_football import ApiFootballClient
from futbol_pred.ingest.api_football_quota import get_absences_batch


class RecordingInjuriesClient(ApiFootballClient):
    def __init__(self, fail_chunk_start=None):
        super().__init__(api_key="test")
        self.calls = []
        self.fail_chunk_start = fail_chunk_start

    def _get(self, path, params):
        self.calls.append((path, dict(params)))
        ids = [int(value) for value in str(params.get("ids") or "").split("-") if value]
        if ids and ids[0] == self.fail_chunk_start:
            raise RuntimeError("quota")
        response = []
        for fixture_id in ids:
            if fixture_id % 2 == 0:
                response.append({
                    "fixture": {"id": fixture_id},
                    "team": {"name": f"Team {fixture_id}"},
                    "player": {
                        "name": f"Player {fixture_id}",
                        "type": "Injury",
                        "reason": "Muscle injury",
                    },
                })
        return {"response": response}


def test_get_absences_batch_agrupa_45_fixtures_en_tres_peticiones():
    client = RecordingInjuriesClient()

    result = get_absences_batch(client, list(range(1, 46)) + [1, 2])

    assert len(client.calls) == 3
    assert [len(params["ids"].split("-")) for _, params in client.calls] == [20, 20, 5]
    assert all(path == "injuries" for path, _ in client.calls)
    assert result[1] == []
    assert result[2][0]["jugador"] == "Player 2"
    assert result[2][0]["source"] == "API-Football"


def test_get_absences_batch_distingue_sin_bajas_de_lote_no_comprobado():
    client = RecordingInjuriesClient(fail_chunk_start=21)

    result = get_absences_batch(client, list(range(1, 41)))

    assert result[1] == []
    assert result[2][0]["jugador"] == "Player 2"
    assert result[21] is None
    assert result[40] is None
