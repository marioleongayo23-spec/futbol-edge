from datetime import datetime, timedelta, timezone

from futbol_pred.ingest.api_football import Fixture
from futbol_pred import historical_seed


def _fixtures():
    out = []
    teams = ["Real Madrid", "Barcelona", "Valencia", "Sevilla"]
    start = datetime(2025, 8, 1, tzinfo=timezone.utc)
    for i in range(60):
        home = teams[i % 4]
        away = teams[(i + 1) % 4]
        out.append(Fixture(
            api_id=i + 1, league="laliga", season=2025,
            kickoff=start + timedelta(days=i), home_team=home, away_team=away,
            status="FINISHED", home_goals=2 if i % 3 else 1, away_goals=1,
            matchday=i // 10 + 1,
        ))
    return out


class FakeResult:
    def __init__(self):
        self.records = []
        prices = {"1": 2.0, "X": 3.5, "2": 4.0}
        for i in range(50):
            actual = "1" if i % 3 else "X"
            self.records.append({
                "kickoff": datetime(2025, 8, 1, tzinfo=timezone.utc).timestamp() + i * 86400,
                "home": "Real Madrid", "away": "Barcelona",
                "probs": {"1": 0.52, "X": 0.27, "2": 0.21},
                "actual": actual, "odds": prices,
            })


def test_seed_usa_temporada_anterior_y_etiqueta_historico(monkeypatch):
    monkeypatch.setattr(historical_seed, "get_fixtures", lambda league, season: _fixtures())
    monkeypatch.setattr(historical_seed, "walk_forward", lambda *args, **kwargs: FakeResult())
    monkeypatch.setattr(
        historical_seed.FootballDataUKClient,
        "get_historical_closing_odds",
        lambda self, league, season: [
            {"home": "Real Madrid", "away": "Barcelona", "closing_odds": {"1x2": {"1": 2.0, "X": 3.5, "2": 4.0}}}
        ],
    )

    seed = historical_seed.prior_season_seed("laliga", 2026)
    assert seed is not None
    assert seed["scope"] == "historical_seed"
    assert seed["evaluation_season"] == 2025
    assert seed["current_season"] == 2026
    assert seed["market_calibration"]["seeded_from_previous_season"] is True
    assert seed["market_calibration"]["n"] == 50
    assert seed["probability_quality"]["model_only"]["n"] == 50
    assert seed["probability_quality"]["market"]["n"] == 50
    assert seed["probability_quality"]["reliability_1"]


def test_seed_falla_limpio_sin_cierres(monkeypatch):
    monkeypatch.setattr(historical_seed, "get_fixtures", lambda league, season: _fixtures())
    monkeypatch.setattr(
        historical_seed.FootballDataUKClient,
        "get_historical_closing_odds",
        lambda self, league, season: [],
    )
    assert historical_seed.prior_season_seed("laliga", 2026) is None


def test_champions_no_finge_seed_sin_fuente_historica_compatible():
    assert historical_seed.prior_season_seed("champions", 2026) is None
