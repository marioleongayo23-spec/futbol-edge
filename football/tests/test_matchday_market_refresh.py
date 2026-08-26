from datetime import datetime

from futbol_pred.matchday_market_refresh import refresh_payload, ttl_minutes


def _event():
    return {
        "id": "evt-1",
        "commence_time": "2026-08-26T19:00:00Z",
        "home_team": "Real Madrid",
        "away_team": "Real Sociedad",
        "bookmakers": [
            {
                "key": "book-a", "title": "Book A", "last_update": "2026-08-26T16:58:00Z",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Real Madrid", "price": 1.80},
                        {"name": "Draw", "price": 3.80},
                        {"name": "Real Sociedad", "price": 4.50},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": 1.95, "point": 2.5},
                        {"name": "Under", "price": 1.90, "point": 2.5},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Real Madrid", "price": 1.91, "point": -0.75},
                        {"name": "Real Sociedad", "price": 1.95, "point": 0.75},
                    ]},
                ],
            },
            {
                "key": "book-b", "title": "Book B", "last_update": "2026-08-26T16:59:00Z",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Real Madrid", "price": 1.82},
                        {"name": "Draw", "price": 3.76},
                        {"name": "Real Sociedad", "price": 4.40},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": 1.97, "point": 2.5},
                        {"name": "Under", "price": 1.89, "point": 2.5},
                    ]},
                ],
            },
        ],
    }


class FakeClient:
    available = True

    def __init__(self, remaining=20000):
        self.quota = {"remaining": remaining, "used": 100, "last_cost": 3}
        self.calls = []

    def featured(self, league):
        self.calls.append(league)
        return [_event()]


def _payload():
    return {
        "generated_at": "2026-08-26T16:00:00+02:00",
        "matches": [{
            "id": "m1",
            "home": "Real Madrid CF",
            "away": "Real Sociedad de Fútbol",
            "league": "LaLiga",
            "kickoff": "2026-08-26T21:00:00+02:00",
            "finished": False,
            "model_probs": [61.0, 23.0, 16.0],
            "probs": [60, 23, 17],
            "markets": {"over_2_5": 0.57},
            "market_calibration": {"model_weight": 0.70, "market_weight": 0.30, "temperature": 1.0},
            "odds": {
                "1x2": {"odds": {"1": 1.90, "X": 3.70, "2": 4.20}},
                "meta": {"opening_1x2": {"1": 1.95, "X": 3.60, "2": 4.00}},
            },
            "value": [{"market": "player_shots", "selection": "Over", "edge": 0.08}],
        }],
    }


def test_ttl_se_acorta_cuanto_mas_cerca_esta_el_partido():
    assert ttl_minutes(10, 20000) == 30
    assert ttl_minutes(4, 20000) == 20
    assert ttl_minutes(2, 20000) == 10
    assert ttl_minutes(1, 20000) == 5


def test_ttl_protege_plan_starter_y_cuota_baja():
    assert ttl_minutes(1, 500) == 15
    assert ttl_minutes(1, 150) == 30
    assert ttl_minutes(1, 50) == 60
    assert ttl_minutes(1, 10) == 90


def test_refresco_actualiza_consenso_value_y_recalibracion_sin_tocar_model_probs():
    payload = _payload()
    client = FakeClient()
    before_model = list(payload["matches"][0]["model_probs"])

    changed, stats = refresh_payload(
        payload,
        now=datetime.fromisoformat("2026-08-26T18:00:00+02:00"),
        client=client,
    )

    match = payload["matches"][0]
    assert changed is True
    assert stats["refreshed"] == 1
    assert client.calls == ["LaLiga"]
    assert match["model_probs"] == before_model
    assert match["odds"]["1x2"]["odds"] == {"1": 1.81, "X": 3.78, "2": 4.45}
    assert match["odds"]["meta"]["latest_1x2"] == {"1": 1.81, "X": 3.78, "2": 4.45}
    assert match["odds"]["meta"]["movement_source"] == "the_odds_api_live"
    assert match["market_live_recalibration"]["after"] == match["probs"]
    assert any(row["market"] == "1x2" for row in match["value"])
    assert any(row["market"] == "ou25" for row in match["value"])
    assert any(row["market"] == "player_shots" for row in match["value"])
    assert payload["source_health"]["the_odds_api"]["remaining"] == 20000


def test_no_reconsulta_si_el_ttl_aun_no_ha_vencido():
    payload = _payload()
    payload["matches"][0]["market_hot_refresh"] = {
        "captured_at": "2026-08-26T17:55:00+02:00"
    }
    client = FakeClient()

    changed, stats = refresh_payload(
        payload,
        now=datetime.fromisoformat("2026-08-26T18:00:00+02:00"),
        client=client,
    )

    assert changed is False
    assert stats["leagues_queried"] == 0
    assert client.calls == []


def test_una_llamada_por_liga_refresca_varios_partidos():
    payload = _payload()
    second = dict(payload["matches"][0])
    second["id"] = "m2"
    payload["matches"].append(second)
    client = FakeClient()

    _, stats = refresh_payload(
        payload,
        now=datetime.fromisoformat("2026-08-26T18:00:00+02:00"),
        client=client,
    )

    assert stats["leagues_queried"] == 1
    assert client.calls == ["LaLiga"]
