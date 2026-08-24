from datetime import datetime, timezone

from futbol_pred.dashboard import _canon, fixture_payload
from futbol_pred.ingest.api_football import Fixture
from futbol_pred.ingest.football_data_uk import _closing_odds


def test_closing_odds_prefiere_media_de_mercado():
    row = {
        "AvgCH": "2.20", "AvgCD": "3.40", "AvgCA": "3.50",
        "B365CH": "2.10", "B365CD": "3.50", "B365CA": "3.60",
    }
    close = _closing_odds(row)
    assert close == {
        "source": "football-data.co.uk",
        "market_source": "market_average",
        "1x2": {"1": 2.2, "X": 3.4, "2": 3.5},
    }


def test_closing_odds_cae_a_bet365_sin_mezclar():
    row = {
        "AvgCH": "2.20", "AvgCD": "", "AvgCA": "3.50",
        "B365CH": "2.10", "B365CD": "3.50", "B365CA": "3.60",
    }
    close = _closing_odds(row)
    assert close["market_source"] == "Bet365"
    assert close["1x2"] == {"1": 2.1, "X": 3.5, "2": 3.6}


def test_finished_payload_expone_cierre_historico_sin_modelo():
    fixture = Fixture(
        api_id=7,
        league="laliga",
        season=2026,
        kickoff=datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc),
        home_team="Real Madrid",
        away_team="Barcelona",
        status="FINISHED",
        home_goals=2,
        away_goals=1,
    )
    close = {
        "source": "football-data.co.uk",
        "market_source": "market_average",
        "1x2": {"1": 2.2, "X": 3.4, "2": 3.5},
    }
    payload = fixture_payload(
        fixture,
        model=None,
        generated_at="2026-08-21T00:00:00+02:00",
        closing_odds_map={(_canon("Real Madrid"), _canon("Barcelona")): close},
    )
    assert payload["result"] == [2, 1]
    assert payload["closing_odds"] == close
