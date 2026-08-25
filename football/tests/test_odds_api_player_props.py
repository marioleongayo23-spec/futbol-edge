from futbol_pred.ingest.odds_api import OddsApiClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_props_fallan_cerrado_sin_clave_y_fuera_de_laliga(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No debe llamar a red")

    monkeypatch.setattr("futbol_pred.ingest.odds_api.requests.get", forbidden)
    assert OddsApiClient(api_key="").get_player_props("laliga", "event") == []
    assert OddsApiClient(api_key="secret").get_player_props("segunda", "event") == []


def test_events_resuelven_id_sin_cuotas(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, dict(params), timeout))
        return FakeResponse([
            {
                "id": "abc123",
                "home_team": "Real Madrid",
                "away_team": "Barcelona",
                "commence_time": "2026-08-30T19:00:00Z",
            },
            {"id": "", "home_team": "Incompleto", "away_team": "Otro"},
        ])

    monkeypatch.setattr("futbol_pred.ingest.odds_api.requests.get", fake_get)
    events = OddsApiClient(api_key="secret").get_events("laliga")

    assert events == [{
        "id": "abc123",
        "home_team": "Real Madrid",
        "away_team": "Barcelona",
        "commence_time": "2026-08-30T19:00:00Z",
    }]
    assert calls[0][0].endswith("/sports/soccer_spain_la_liga/events")
    assert calls[0][1]["dateFormat"] == "iso"


def test_props_normalizan_remates_sot_y_tarjeta(monkeypatch):
    calls = []
    payload = {
        "id": "evt1",
        "home_team": "Real Madrid",
        "away_team": "Barcelona",
        "bookmakers": [{
            "key": "fanduel",
            "title": "FanDuel",
            "markets": [
                {
                    "key": "player_shots",
                    "last_update": "2026-08-25T03:00:00Z",
                    "outcomes": [
                        {"name": "Over", "description": "Kylian Mbappe", "price": 1.80, "point": 2.5},
                        {"name": "Under", "description": "Kylian Mbappe", "price": 2.00, "point": 2.5},
                    ],
                },
                {
                    "key": "player_shots_on_target",
                    "outcomes": [
                        {"name": "Over", "description": "Kylian Mbappe", "price": 1.65, "point": 0.5},
                        {"name": "Under", "description": "Kylian Mbappe", "price": 2.20, "point": 0.5},
                    ],
                },
                {
                    "key": "player_to_receive_card",
                    "outcomes": [
                        {"name": "Yes", "description": "Dani Carvajal", "price": 3.10},
                        {"name": "No", "description": "Dani Carvajal", "price": 1.32},
                    ],
                },
                {
                    "key": "player_shots",
                    "outcomes": [
                        {"name": "Over", "description": "", "price": 1.50, "point": 1.5},
                        {"name": "Maybe", "description": "Jugador X", "price": 1.50, "point": 1.5},
                        {"name": "Over", "description": "Jugador Y", "price": 1.00, "point": 1.5},
                    ],
                },
            ],
        }],
    }

    def fake_get(url, params, timeout):
        calls.append((url, dict(params), timeout))
        return FakeResponse(payload)

    monkeypatch.setattr("futbol_pred.ingest.odds_api.requests.get", fake_get)
    rows = OddsApiClient(api_key="secret").get_player_props("laliga", "evt1")

    assert len(rows) == 6
    shots = [row for row in rows if row.metric == "r"]
    assert [(row.side, row.point, row.odds) for row in shots] == [
        ("over", 2.5, 1.8),
        ("under", 2.5, 2.0),
    ]
    card = [row for row in rows if row.metric == "t"]
    assert [(row.side, row.point) for row in card] == [("over", 0.5), ("under", 0.5)]
    assert all(row.bookmaker == "fanduel" for row in rows)
    assert calls[0][0].endswith("/sports/soccer_spain_la_liga/events/evt1/odds")
    assert calls[0][1]["regions"] == "us"
    assert "player_shots_on_target" in calls[0][1]["markets"]


def test_props_ignoran_lista_de_mercados_no_soportada(monkeypatch):
    monkeypatch.setattr(
        "futbol_pred.ingest.odds_api.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe llamar a red")),
    )
    client = OddsApiClient(api_key="secret")
    assert client.get_player_props("laliga", "evt", markets=["player_fouls"]) == []
