"""Orquestación: ingesta -> ajuste del modelo -> predicción -> value bets.

Es la pieza que ejecuta el cron. Todo el flujo funciona offline (con datos de
ejemplo) si no hay claves, para poder probar el pipeline de punta a punta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import settings
from .ingest.api_football import ApiFootballClient, Fixture
from .ingest.football_data import FootballDataClient
from .model import DixonColesModel
from .value import BankrollPolicy, scan_market


def get_fixtures(league: str, season: int | None = None) -> list[Fixture]:
    """Fuente de fixtures con prioridad y fallback gratis.

    football-data.org (LaLiga, Champions) → OpenFootball (Segunda, gratis) →
    API-Football. En modo offline, datos de ejemplo. OpenFootball se consulta
    en modo estricto (solo la temporada pedida) para no mezclar temporadas.
    """
    fd = FootballDataClient()
    if not fd.offline:
        try:
            fx = fd.get_matches(league, season=season)
            if fx:
                return fx
        except Exception:
            pass  # p. ej. Segunda no está en el plan free (403): probamos otra
        from .ingest.openfootball import OpenFootballClient

        of = OpenFootballClient().get_matches(
            league, season=season or settings.season
        )
        if of:
            return of
        af = ApiFootballClient()
        return [] if af.offline else af.get_fixtures(league, season=season)
    return ApiFootballClient().get_fixtures(league, season=season)


@dataclass
class MatchPrediction:
    home: str
    away: str
    kickoff: datetime | None
    one_x_two: dict[str, float]
    over_under: dict[str, float]
    btts: dict[str, float]
    expected_goals: tuple[float, float]


def fit_model_from_fixtures(
    fixtures: list[Fixture], as_of: datetime | None = None
) -> DixonColesModel:
    """Ajusta Dixon-Coles usando solo partidos ya jugados (FT)."""
    played = [f for f in fixtures if f.home_goals is not None]
    if not played:
        raise ValueError("No hay partidos jugados para ajustar el modelo")

    as_of = as_of or datetime.utcnow()
    home_teams, away_teams, hg, ag, days = [], [], [], [], []
    for f in played:
        home_teams.append(f.home_team)
        away_teams.append(f.away_team)
        hg.append(f.home_goals)
        ag.append(f.away_goals)
        ko = f.kickoff.replace(tzinfo=None) if f.kickoff.tzinfo else f.kickoff
        days.append(max(0.0, (as_of - ko).total_seconds() / 86400))

    model = DixonColesModel()
    model.fit(home_teams, away_teams, hg, ag, days_ago=days)
    return model


def predict_match(
    model: DixonColesModel, home: str, away: str, kickoff: datetime | None = None
) -> MatchPrediction:
    sm = model.predict_matrix(home, away)
    return MatchPrediction(
        home=home,
        away=away,
        kickoff=kickoff,
        one_x_two=sm.one_x_two(),
        over_under={
            "over_2.5": sm.over(2.5),
            "under_2.5": sm.under(2.5),
            "over_1.5": sm.over(1.5),
            "over_3.5": sm.over(3.5),
        },
        btts=sm.btts(),
        expected_goals=sm.expected_goals(),
    )


def run_pipeline(league: str = "laliga", season: int | None = None) -> dict:
    """Ejecuta el flujo completo para una liga y devuelve un informe."""
    fd = FootballDataClient()
    fixtures = get_fixtures(league, season=season)
    model = fit_model_from_fixtures(fixtures)

    # Predice el "próximo enfrentamiento" de ejemplo entre los dos primeros.
    teams = sorted(model.attack, key=lambda t: model.attack[t], reverse=True)
    report = {
        "league": league,
        "season": season or settings.season,
        "offline": fd.offline and ApiFootballClient().offline,
        "n_fixtures": len(fixtures),
        "teams_ranked_by_attack": teams[:8],
        "sample_prediction": None,
    }
    if len(teams) >= 2:
        pred = predict_match(model, teams[0], teams[1])
        report["sample_prediction"] = {
            "match": f"{pred.home} vs {pred.away}",
            "1x2": {k: round(v, 3) for k, v in pred.one_x_two.items()},
            "over_under": {k: round(v, 3) for k, v in pred.over_under.items()},
            "btts": {k: round(v, 3) for k, v in pred.btts.items()},
            "xg": [round(x, 2) for x in pred.expected_goals],
        }
    return report


def fixtures_to_matches(
    fixtures: list[Fixture], teams_per_round: int | None = None
) -> list[dict]:
    """Convierte fixtures jugados al formato de dict del backtest.

    Si los fixtures no traen jornada, se sintetiza agrupando en rondas de
    ``teams_per_round`` partidos por orden cronológico (suficiente para el
    walk-forward de demostración).
    """
    played = sorted(
        [f for f in fixtures if f.home_goals is not None], key=lambda f: f.kickoff
    )
    out = []
    for i, f in enumerate(played):
        # Preferimos la jornada real del fixture; si no la trae, la sintetizamos.
        md = f.matchday
        if md is None:
            md = (i // teams_per_round + 1) if teams_per_round else None
        out.append({
            "home": f.home_team,
            "away": f.away_team,
            "home_goals": f.home_goals,
            "away_goals": f.away_goals,
            "matchday": md,
            "stage": f.stage,
            "kickoff": f.kickoff.timestamp(),
            "status": "FINISHED",
            "competition": f.league,
        })
    return out


def run_backtest(league: str = "laliga", season: int | None = None) -> dict:
    """Walk-forward comparando baseline vs Elo vs Dixon-Coles en una liga."""
    from .backtest import (
        BaselineRates,
        DixonColesPredictor,
        EloPredictor,
        compare_predictors,
    )
    from .config import LEAGUE_META

    tpr = LEAGUE_META.get(league, {}).get("teams_per_round")
    fixtures = get_fixtures(league, season=season)
    matches = fixtures_to_matches(fixtures, teams_per_round=tpr)
    comp = compare_predictors(matches, {
        "baseline": BaselineRates(),
        "elo": EloPredictor(),
        "dixon_coles": DixonColesPredictor(min_matches=30),
    }, min_train_rounds=3)
    return {
        "league": league,
        "season": season or settings.season,
        "n_matches": len(matches),
        "metrics": {k: {m: round(v, 4) for m, v in vals.items()}
                    for k, vals in comp.items()},
    }


def value_report(
    probs: dict[str, float], odds: dict[str, float], market: str = "1x2"
) -> list[dict]:
    policy = BankrollPolicy(
        kelly_multiplier=settings.kelly_multiplier, min_edge=settings.min_edge
    )
    bets = scan_market(
        probs, odds, market, bankroll=settings.bankroll, policy=policy,
        min_edge=settings.min_edge,
    )
    return [
        {
            "market": b.market,
            "selection": b.selection,
            "model_prob": round(b.model_prob, 3),
            "odds": b.odds,
            "fair_odds": round(b.fair_odds, 2),
            "edge": round(b.edge, 3),
            "stake": b.stake,
        }
        for b in bets
    ]
