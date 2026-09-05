"""El probe hace red solo en el cron; aquí verificamos los summarizers PUROS
(parseo de las respuestas) con formas canónicas de cada fuente."""

from futbol_pred.ingest.source_probe import (
    summarize_sofascore_event,
    summarize_flashscore,
)


def test_summarize_sofascore_event_extrae_campos_valiosos():
    detail = {"event": {
        "referee": {"name": "Jesús Gil Manzano"},
        "homeTeam": {"name": "Athletic"},
        "awayTeam": {"name": "Atlético"},
    }}
    lineups = {
        "confirmed": True,
        "home": {
            "formation": "4-4-2",
            "players": [
                {"player": {"name": "Unai Simón"}, "statistics": {"rating": 7.3}},
                {"player": {"name": "Iñaki Williams"}, "statistics": {"rating": 6.9}},
            ],
            "missingPlayers": [{"player": {"name": "Lesionado"}, "reason": 0}],
        },
        "away": {"formation": "3-5-2", "players": []},
    }
    statistics = {"statistics": [{
        "period": "ALL",
        "groups": [{
            "groupName": "Expected",
            "statisticsItems": [
                {"name": "Expected goals", "key": "expectedGoals", "home": "1.8", "away": "0.7"},
            ],
        }, {
            "groupName": "Shots",
            "statisticsItems": [{"name": "Total shots", "home": "12", "away": "6"}],
        }],
    }]}

    found = summarize_sofascore_event(detail, lineups, statistics)

    assert found["referee"] == "Jesús Gil Manzano"
    assert found["match"] == "Athletic vs Atlético"
    assert found["player_ratings"] is True
    assert found["player_rating_sample"]["rating"] == 7.3
    assert found["missing_players"] is True
    assert set(found["formations"]) == {"4-4-2", "3-5-2"}
    assert found["xg"] == {"home": "1.8", "away": "0.7"}
    assert "Expected" in found["stat_groups"] and "Shots" in found["stat_groups"]


def test_summarize_sofascore_event_sin_datos_no_inventa():
    found = summarize_sofascore_event({}, {}, {})
    assert found == {} or "referee" not in found
    assert "player_ratings" not in found
    assert "xg" not in found


def test_summarize_flashscore_detecta_feed_ofuscado():
    feed = {"ok": True, "status": 200, "len": 40,
            "body": "AA÷abc¬AB÷1¬AD÷1700000000~".encode("utf-8")}
    out = summarize_flashscore(feed)
    assert out["looks_like_fs_feed"] is True
    assert out["looks_like_json"] is False


def test_summarize_flashscore_json_plano():
    feed = {"ok": True, "status": 200, "len": 12, "body": b'{"a": 1}'}
    out = summarize_flashscore(feed)
    assert out["looks_like_json"] is True
    assert out["looks_like_fs_feed"] is False
