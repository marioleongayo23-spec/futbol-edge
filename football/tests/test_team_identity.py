from datetime import datetime
from futbol_pred.normalize import same_team
from futbol_pred.operational import _side_for
from futbol_pred.matchday_current_squads import _find_named_squad, _cached_squad, refresh_payload, MADRID
from futbol_pred.matchday_player_props_fill import attach_player_markets
from futbol_pred.ingest.api_football import ApiFootballClient
from futbol_pred.ingest.api_football_players import _team_id


def test_barcelona_and_espanyol_never_share_identity():
    assert same_team("FC Barcelona", "Barcelona")
    assert same_team("RCD Espanyol de Barcelona", "Espanyol")
    assert not same_team("FC Barcelona", "RCD Espanyol de Barcelona")
    assert not same_team("Barcelona", "Barcelona B")
    assert not same_team("Real Sociedad", "Real Sociedad B")
    assert _side_for("Espanyol", "FC Barcelona", "RCD Espanyol de Barcelona") == "visitante"
    squads = {"RCD Espanyol de Barcelona": [{"name": "Espanyol player"}], "FC Barcelona": [{"name": "Barça player"}]}
    assert _find_named_squad(squads, "Barcelona")[1][0]["name"] == "Barça player"


def test_api_search_requires_unique_club_match():
    class Client:
        offline = False
        def _get(self, path, params):
            return {"response": [{"team": {"id": 540, "name": "Espanyol"}}]}
    client = Client()
    assert _team_id(client, "FC Barcelona") is None
    assert ApiFootballClient.get_squad(client, "FC Barcelona") == []


def test_cached_rosters_from_substring_matching_are_not_reused():
    now = datetime(2026, 9, 6, 10, tzinfo=MADRID)
    rows = [{"player": f"P{i}", "team": "Barcelona", "current_squad_member": True,
             "current_squad_checked_at": now.isoformat()} for i in range(11)]
    assert _cached_squad({"players": {"laliga": {"players": rows}}}, "laliga", "Barcelona", now) == ([], None)


def test_roster_refresh_repairs_barca_lineup_and_all_top_fives():
    now = datetime(2026, 9, 6, 10, tzinfo=MADRID)
    def roster(prefix):
        return [{"name": f"{prefix}{i}", "position": "Goalkeeper" if i == 0 else "Defender"} for i in range(11)]
    class FD:
        offline = False
        def get_team_meta(self, league, season):
            # Espanyol first reproduces the original ambiguous lookup.
            return {"RCD Espanyol de Barcelona": {"squad": roster("E")}, "FC Barcelona": {"squad": roster("B")}}
    class API:
        offline = True
    match = {"id": "derby", "home": "FC Barcelona", "away": "RCD Espanyol de Barcelona", "league": "LaLiga",
             "kickoff": "2026-09-06T16:00:00+02:00", "finished": False, "xg": [2, 1],
             "alineacion": {"status": "estimado", "local": [f"E{i}" for i in range(11)],
                            "visitante": [f"E{i}" for i in range(11)],
                            "posiciones_local": ["POR"] + ["DFC"] * 10,
                            "posiciones_visitante": ["POR"] + ["DFC"] * 10}}
    payload = {"matches": [match], "players": {"laliga": {"players": []}}}
    refresh_payload(payload, now=now, football_client=API(), football_data_client=FD())
    assert set(match["alineacion"]["local"]) == {f"B{i}" for i in range(11)}
    assert set(match["alineacion"]["visitante"]) == {f"E{i}" for i in range(11)}
    attach_player_markets([match], now)
    for metric in match["player_markets"]["metrics"]:
        assert all(p["jugador"].startswith("B") for p in metric["home"])
        assert all(p["jugador"].startswith("E") for p in metric["away"])
