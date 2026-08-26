from futbol_pred.hot_refresh_metered import ApiFootballUsageMeter
from futbol_pred.ingest.api_football import BASE_URL


class FakeResponse:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_mide_solo_api_football_y_agrupa_por_endpoint():
    responses = iter([
        FakeResponse({
            "x-ratelimit-requests-limit": "7500",
            "x-ratelimit-requests-remaining": "7498",
            "X-RateLimit-Limit": "300",
            "X-RateLimit-Remaining": "298",
        }),
        FakeResponse({
            "x-ratelimit-requests-remaining": "7497",
            "X-RateLimit-Remaining": "297",
        }),
        FakeResponse(),
    ])

    def fake_get(url, *args, **kwargs):
        return next(responses)

    meter = ApiFootballUsageMeter(fake_get)
    meter.request(f"{BASE_URL}/fixtures", params={"date": "2026-08-26"})
    meter.request(f"{BASE_URL}/fixtures/lineups", params={"fixture": 123})
    meter.request("https://api.open-meteo.com/v1/forecast")

    snapshot = meter.snapshot()
    assert snapshot["requests_total"] == 2
    assert snapshot["requests_by_endpoint"] == {
        "fixtures": 1,
        "fixtures/lineups": 1,
    }
    assert snapshot["daily_limit"] == 7500
    assert snapshot["daily_remaining"] == 7497
    assert snapshot["minute_limit"] == 300
    assert snapshot["minute_remaining"] == 297


def test_headers_ausentes_no_borran_la_ultima_cuota_conocida():
    responses = iter([
        FakeResponse({"x-ratelimit-requests-remaining": "99"}),
        FakeResponse({}),
    ])

    meter = ApiFootballUsageMeter(lambda *args, **kwargs: next(responses))
    meter.request(f"{BASE_URL}/fixtures")
    meter.request(f"{BASE_URL}/injuries")

    snapshot = meter.snapshot()
    assert snapshot["requests_total"] == 2
    assert snapshot["daily_remaining"] == 99
    assert snapshot["requests_by_endpoint"]["injuries"] == 1
