"""Orquestación: ingesta -> ajuste del modelo -> predicción -> value bets.

Es la pieza que ejecuta el cron. El modo demo requiere una opción explícita;
una fuente sin credenciales nunca introduce partidos sintéticos en producción.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings
from .ingest.api_football import ApiFootballClient, Fixture
from .ingest.football_data import FootballDataClient
from .model import DixonColesModel
from .prediction_snapshots import MODEL_VERSION
from .value import BankrollPolicy, scan_market


def _dbg(msg: str) -> None:
    import os
    import sys

    if os.environ.get("DEBUG_INGEST"):
        print(f"[ingest] {msg}", file=sys.stderr)


def get_fixtures(league: str, season: int | None = None, *, demo: bool = False) -> list[Fixture]:
    """Resolve a season through independent providers, without synthetic fallback.

    Credential availability for one adapter must not gate another adapter.
    Demo fixtures are available only through an explicit development option.
    A failed/empty provider advances to the next; a valid response is selected
    as one coherent calendar, never merged by loose team-name similarity.
    """
    from .ingest.openfootball import OpenFootballClient
    from .ingest.football_data_uk import FootballDataUKClient

    season = season or settings.season
    fd, af = FootballDataClient(), ApiFootballClient()
    if demo:
        from .ingest.api_football import _sample_fixtures
        return _sample_fixtures(league, season)
    providers = []
    if not fd.offline:
        providers.append(("football-data", lambda: fd.get_matches(league, season=season)))
    if not af.offline:
        providers.append(("api-football", lambda: af.get_fixtures(league, season=season)))
    providers.extend([
        ("openfootball", lambda: OpenFootballClient().get_matches(league, season=season)),
        ("football-data.co.uk", lambda: FootballDataUKClient().get_fixtures(league, season)),
    ])
    for name, fetch in providers:
        try:
            fixtures = fetch()
            seen, valid = set(), []
            for fixture in fixtures or []:
                if (fixture.season != season or fixture.league != league
                        or not fixture.home_team or not fixture.away_team
                        or fixture.home_team == fixture.away_team or not fixture.kickoff):
                    continue
                key = (fixture.home_team, fixture.away_team, fixture.kickoff.date())
                if key not in seen:
                    seen.add(key)
                    valid.append(fixture)
            _dbg(f"{league} {season}: {name} -> {len(valid)} valid fixtures")
            if valid:
                return valid
        except Exception as exc:
            _dbg(f"{league} {season}: {name} ERROR {type(exc).__name__}")
    return []


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
    fixtures: list[Fixture],
    as_of: datetime | None = None,
    name_fn=None,
) -> DixonColesModel:
    """Ajusta Dixon-Coles usando solo partidos ya jugados (FT).

    ``name_fn`` (opcional) mapea el nombre de cada equipo antes de ajustar
    (p. ej. ``canonical_team``), para que un mismo club en distintas fuentes o
    divisiones enlace bajo un único identificador.
    """
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    as_of = utc(as_of or datetime.now(timezone.utc))
    played = [f for f in fixtures if f.home_goals is not None and f.away_goals is not None
              and utc(f.kickoff) < as_of and str(f.status).upper() in {"FINISHED", "FT", "AET", "PEN", "AWARDED"}]
    if not played:
        raise ValueError("No hay partidos jugados para ajustar el modelo")

    name_fn = name_fn or (lambda n: n)
    home_teams, away_teams, hg, ag, days = [], [], [], [], []
    for f in played:
        home_teams.append(name_fn(f.home_team))
        away_teams.append(name_fn(f.away_team))
        hg.append(f.home_goals)
        ag.append(f.away_goals)
        ko = utc(f.kickoff)
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


def run_pipeline(league: str = "laliga", season: int | None = None, *, demo: bool = False) -> dict:
    """Ejecuta el flujo completo para una liga y devuelve un informe."""
    fixtures = get_fixtures(league, season=season, demo=demo)
    model = fit_model_from_fixtures(fixtures)

    # Predice el "próximo enfrentamiento" de ejemplo entre los dos primeros.
    teams = sorted(model.attack, key=lambda t: model.attack[t], reverse=True)
    report = {
        "league": league,
        "season": season or settings.season,
        "offline": demo,
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
        [f for f in fixtures if f.home_goals is not None and f.away_goals is not None
         and str(f.status).upper() in {"FINISHED", "FT", "AET", "PEN", "AWARDED"}],
        key=lambda f: f.kickoff,
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
            "season": f.season,
            "available_at": f.kickoff.timestamp() + 3 * 3600,
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


def run_model_report(league: str = "laliga", season: int | None = None) -> dict | None:
    """Informe de calibración y comparación de modelos (walk-forward).

    Devuelve, para la liga indicada, las métricas de baseline/Elo/Dixon-Coles
    y la tabla de calibración (prob. predicha vs frecuencia real) del modelo en
    producción (Dixon-Coles) para los tres signos 1/X/2. None si no hay datos.
    """
    from .backtest import (
        BaselineRates,
        DixonColesPredictor,
        EloPredictor,
        fit_walk_forward_ensemble,
        fit_walk_forward_residual,
        walk_forward,
    )
    from .config import LEAGUE_META

    try:
        tpr = LEAGUE_META.get(league, {}).get("teams_per_round")
        fixtures = get_fixtures(league, season=season)
        matches = fixtures_to_matches(fixtures, teams_per_round=tpr)
    except Exception:
        return None
    if not matches:
        return None

    predictors = {
        "baseline": BaselineRates(),
        "elo": EloPredictor(),
        "dixon_coles": DixonColesPredictor(min_matches=30),
    }
    metrics: dict = {}
    dc_result = None
    elo_result = None
    for name, pred in predictors.items():
        try:
            res = walk_forward(matches, pred, min_train_rounds=3)
        except Exception:
            continue
        m = res.metrics()
        if not m.get("n"):
            continue
        metrics[name] = {k: (round(v, 4) if isinstance(v, float) else v)
                         for k, v in m.items()}
        if name == "dixon_coles":
            dc_result = res
        elif name == "elo":
            elo_result = res

    ensemble = None
    residual = None
    if dc_result is not None and elo_result is not None:
        ensemble = fit_walk_forward_ensemble(dc_result.records, elo_result.records)
        residual = fit_walk_forward_residual(dc_result.records, elo_result.records)
        if ensemble and ensemble.get("validation", {}).get("n"):
            metrics["ensemble"] = {
                key: (round(value, 4) if isinstance(value, float) else value)
                for key, value in ensemble["validation"].items()
            }
        if residual and residual.get("validation", {}).get("n"):
            metrics["residual"] = {
                key: (round(value, 4) if isinstance(value, float) else value)
                for key, value in residual["validation"].items()
            }

    if not metrics:
        return None

    calibration = {}
    n_pred = 0
    if dc_result is not None:
        n_pred = len(dc_result.predictions)
        for sign in ("1", "X", "2"):
            calibration[sign] = dc_result.calibration(selection=sign, bins=10)

    return {
        "league": league,
        "season": season or settings.season,
        "n_matches": len(matches),
        "n_predicciones": n_pred,
        "model_version": MODEL_VERSION,
        "predictors": metrics,
        "calibration": calibration,
        "ensemble": ensemble,
        "residual": residual,
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
