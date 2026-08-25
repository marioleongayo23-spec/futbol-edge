from futbol_pred.dashboard import _merge_lineup_players
from futbol_pred.ingest.api_football_players import props_for_official_starters


def test_props_keep_season_rates_for_player_profiles():
    rates = [{
        "player": "Player One",
        "player_id": 7,
        "profile": {"age": 24, "photo": "https://example.test/p.jpg"},
        "position": "Attacker",
        "rating": 7.2,
        "pass_accuracy_pct": 81.0,
        "minutes": 900,
        "appearances": 12,
        "starts": 10,
        "starter_rate": 10 / 12,
        "expected_start_minutes": 81.0,
        "per90": {"g": .5, "a": .2, "r": 3.0, "rp": 1.2, "fc": .8, "fr": 1.4, "t": .1},
        "per90_extended": {"key_passes": 1.6, "duels_won": 3.2, "dribbles_success": 1.8},
        "source": "API-Football · players",
    }]
    rows = props_for_official_starters(["Player One"], rates)
    assert rows[0]["season"]["minutes"] == 900
    assert rows[0]["season"]["per90"]["g"] == .5
    assert rows[0]["season"]["per90_extended"]["key_passes"] == 1.6


def test_merge_lineup_enriches_existing_player_without_overwriting_aggregates():
    players = {"laliga": {"label": "LaLiga", "rankings": {}, "players": [{
        "player": "Player One", "team": "Club Uno", "position": "Attacker",
        "goals": 8, "assists": 3, "shots": 50, "yc": 2, "min": 1200,
        "source": "Understat",
    }]}}
    matches = [{
        "league": "LaLiga", "home": "Club Uno", "away": "Club Dos",
        "alineacion": {
            "local": ["Player One"], "visitante": [],
            "posiciones_local": ["Attacker"], "posiciones_visitante": [],
            "clave_local": [{
                "jugador": "Player One", "g": .4, "a": .1, "r": 2.8, "rp": 1.1,
                "fc": .7, "fr": 1.3, "t": .05, "min": 82, "tit": 1.0,
                "sample_minutes": 900, "player_id": 7,
                "profile": {"age": 24, "photo": "https://example.test/p.jpg"},
                "position": "Attacker", "rating": 7.2, "pass_accuracy_pct": 81.0,
                "extended": {"key_passes": 1.4},
                "season": {"minutes": 900, "per90": {"g": .5}, "per90_extended": {"key_passes": 1.6}},
                "source": "API-Football · players",
            }],
            "clave_visitante": [], "status": "oficial", "provider": "API-Football",
        },
    }]
    out = _merge_lineup_players(players, matches)
    row = out["laliga"]["players"][0]
    assert row["goals"] == 8
    assert row["assists"] == 3
    assert row["source"] == "Understat"
    assert row["profile"]["age"] == 24
    assert row["season"]["per90"]["g"] == .5
    assert row["expected_match"]["r"] == 2.8
    assert row["lineup_status"] == "oficial"
