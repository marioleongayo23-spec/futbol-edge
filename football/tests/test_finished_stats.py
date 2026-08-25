from datetime import datetime, timedelta

from futbol_pred.finished_stats import attach_finished_stats


class FinishedClient:
    offline = False

    def __init__(self):
        self.detail_calls = []
        self.find_calls = []

    def find_fixture(self, home, away, kickoff):
        self.find_calls.append((home, away, kickoff))
        return {"fixture": {"id": 77}}

    def get_fixture_details(self, ids):
        self.detail_calls.append(list(ids))
        return {
            77: {
                "fixture": {"id": 77, "status": {"short": "FT"}, "referee": "Árbitro X"},
                "teams": {
                    "home": {"name": "Atletico Madrid"},
                    "away": {"name": "Valencia CF"},
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
                        ],
                    },
                    {
                        "team": {"name": "Valencia CF"},
                        "statistics": [
                            {"type": "Total Shots", "value": 9},
                            {"type": "Shots on Goal", "value": 3},
                            {"type": "Corner Kicks", "value": 4},
                            {"type": "Fouls", "value": 15},
                            {"type": "Yellow Cards", "value": 4},
                            {"type": "Red Cards", "value": 1},
                        ],
                    },
                ],
            }
        }


def _match(now):
    return {
        "id": "m1",
        "league": "LaLiga",
        "date": (now - timedelta(hours=3)).date().isoformat(),
        "home": "Atlético Madrid",
        "away": "Valencia",
        "kickoff": (now - timedelta(hours=3)).isoformat(),
        "finished": True,
        "result": [2, 1],
        "alineacion": {"status": "confirmado", "official_fixture_id": 77},
    }


def test_refresca_stats_finales_aunque_el_once_ya_este_confirmado():
    now = datetime.fromisoformat("2026-08-25T06:00:00+02:00")
    match = _match(now)
    client = FinishedClient()

    assert attach_finished_stats([match], now, client=client) == 1

    assert client.find_calls == []  # reutiliza el fixture id del once oficial
    assert client.detail_calls == [[77]]
    assert match["statsReal"]["goals"] == {"home": 2, "away": 1, "total": 3}
    assert match["statsReal"]["shots"] == {"home": 16, "away": 9, "total": 25}
    assert match["statsReal"]["sot"] == {"home": 7, "away": 3, "total": 10}
    assert match["statsReal"]["corners"] == {"home": 8, "away": 4, "total": 12}
    assert match["statsReal"]["fouls"] == {"home": 11, "away": 15, "total": 26}
    assert match["statsReal"]["yellows"] == {"home": 2, "away": 4, "total": 6}
    assert match["statsReal"]["reds"] == {"home": 0, "away": 1, "total": 1}
    assert match["statsRealSource"] == "API-Football · final"
    assert match["official_context"]["referee"] == "Árbitro X"


def test_no_acepta_estadisticas_live_como_finales():
    now = datetime.fromisoformat("2026-08-25T06:00:00+02:00")
    client = FinishedClient()
    original = client.get_fixture_details

    def live(ids):
        data = original(ids)
        data[77]["fixture"]["status"]["short"] = "2H"
        return data

    client.get_fixture_details = live
    match = _match(now)

    assert attach_finished_stats([match], now, client=client) == 0
    assert "statsReal" not in match


def test_stats_ya_completas_no_consumen_api():
    now = datetime.fromisoformat("2026-08-25T06:00:00+02:00")
    client = FinishedClient()
    match = _match(now)
    match["statsReal"] = {
        key: {"home": 1, "away": 1, "total": 2}
        for key in ("shots", "sot", "corners", "fouls", "yellows")
    }

    assert attach_finished_stats([match], now, client=client) == 0
    assert client.detail_calls == []
    assert client.find_calls == []


def test_stats_finales_del_feed_anterior_se_heredan_sin_reconsultar():
    now = datetime.fromisoformat("2026-08-25T06:00:00+02:00")
    client = FinishedClient()
    current = _match(now)
    previous = _match(now)
    previous["statsReal"] = {
        "shots": {"home": 16, "away": 9, "total": 25},
        "sot": {"home": 7, "away": 3, "total": 10},
        "corners": {"home": 8, "away": 4, "total": 12},
        "fouls": {"home": 11, "away": 15, "total": 26},
        "yellows": {"home": 2, "away": 4, "total": 6},
    }
    previous["statsRealSource"] = "API-Football · final"
    previous["statsRealUpdatedAt"] = "2026-08-25T00:30:00+02:00"

    assert attach_finished_stats(
        [current], now, client=client, previous_matches=[previous]
    ) == 0
    assert current["statsReal"]["shots"]["total"] == 25
    assert current["statsRealSource"] == "API-Football · final"
    assert client.detail_calls == []
    assert client.find_calls == []


def test_partido_antiguo_fuera_de_ventana_no_se_reconsulta():
    now = datetime.fromisoformat("2026-08-25T06:00:00+02:00")
    client = FinishedClient()
    match = _match(now)
    match["kickoff"] = (now - timedelta(days=5)).isoformat()

    assert attach_finished_stats([match], now, client=client, lookback_days=3) == 0
    assert client.detail_calls == []
