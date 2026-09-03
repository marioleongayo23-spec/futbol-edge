"""Árbitro desde football-data.org (campo ``referees``) y su efecto en la ficha:
enciende el perfil del árbitro y el ajuste de tarjetas/faltas del Bloque 2."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone, timedelta

from futbol_pred.ingest.football_data import FootballDataClient
from futbol_pred.ingest.api_football import Fixture
from futbol_pred.ingest.football_data_uk import MatchStats
from futbol_pred.model.stats_markets import StatsPredictor
from futbol_pred.model.referee_adjustment import RefereeAdjustmentModel
from futbol_pred.pipeline import fit_model_from_fixtures
from futbol_pred.dashboard import fixture_payload, _canon

warnings.simplefilter("ignore")


def test_referee_extrae_el_principal():
    m = {"referees": [
        {"name": "Asistente 1", "type": "ASSISTANT_REFEREE_N1"},
        {"name": "Jesús Gil Manzano", "type": "REFEREE"},
    ]}
    assert FootballDataClient._referee(m) == "Jesús Gil Manzano"


def test_referee_vacio_si_no_hay():
    assert FootballDataClient._referee({"referees": []}) is None
    assert FootballDataClient._referee({}) is None


def test_parse_rellena_referee():
    m = {"id": 1, "utcDate": "2026-09-05T18:00:00Z", "homeTeam": {"name": "A"},
         "awayTeam": {"name": "B"}, "status": "SCHEDULED", "score": {"fullTime": {}},
         "referees": [{"name": "Gil Manzano", "type": "REFEREE"}]}
    assert FootballDataClient._parse(m, "laliga", 2026).referee == "Gil Manzano"


def test_fixture_payload_enciende_arbitro():
    teams = ["Alpha", "Beta", "Gamma", "Delta"]
    start = datetime(2024, 8, 1, tzinfo=timezone.utc)
    rows, fx, d = [], [], 0
    for _ in range(6):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                d += 1
                k = start + timedelta(days=d)
                rows.append(MatchStats(h, a, {"goals": (1, 1), "shots": (12, 10),
                                              "corners": (5, 4), "fouls": (14, 12),
                                              "yellows": (3, 2)}, kickoff=k, referee="Pepe Prieto"))
                fx.append(Fixture(api_id=d, league="laliga", season=2026, kickoff=k,
                                  home_team=h, away_team=a, status="FINISHED",
                                  home_goals=1, away_goals=1, source="t"))
    stats = StatsPredictor().fit(rows, fit_pseudo_xg=False)
    stats.referee_model = RefereeAdjustmentModel().fit(
        rows, accepted_stats={"yellows", "fouls"}, auto_validate=False)
    model = fit_model_from_fixtures(fx, name_fn=_canon)
    up = Fixture(api_id=999, league="laliga", season=2026,
                 kickoff=datetime(2026, 9, 5, 18, tzinfo=timezone.utc),
                 home_team="Alpha", away_team="Beta", status="SCHEDULED",
                 source="t", referee="Pepe Prieto")
    p = fixture_payload(up, model, "2026-09-05T00:00:00+02:00", stats=stats)
    oc = p.get("official_context") or {}
    assert oc.get("referee") == "Pepe Prieto"
    assert oc.get("source") == "football-data.org"
    assert oc.get("provider") == "football-data.org"
    assert oc.get("referee_profile")  # ≥6 partidos del árbitro → hay perfil
    # el ajuste (aceptado) marca el mercado de tarjetas
    yellows = next((mk for mk in p.get("markets_detail", []) if mk["stat"] == "yellows"), None)
    assert yellows and yellows.get("referee_moved") is True


def test_fixture_payload_sin_referee_no_pone_contexto():
    teams = ["Alpha", "Beta", "Gamma"]
    start = datetime(2024, 8, 1, tzinfo=timezone.utc)
    fx, d = [], 0
    for _ in range(6):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                d += 1
                fx.append(Fixture(api_id=d, league="laliga", season=2026,
                                  kickoff=start + timedelta(days=d), home_team=h, away_team=a,
                                  status="FINISHED", home_goals=1, away_goals=1, source="t"))
    model = fit_model_from_fixtures(fx, name_fn=_canon)
    up = Fixture(api_id=999, league="laliga", season=2026,
                 kickoff=datetime(2026, 9, 5, 18, tzinfo=timezone.utc),
                 home_team="Alpha", away_team="Beta", status="SCHEDULED", source="t")
    p = fixture_payload(up, model, "2026-09-05T00:00:00+02:00")
    assert "official_context" not in p
