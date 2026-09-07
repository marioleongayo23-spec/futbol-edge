"""Informe pesado P2.3: challenger 1X2 con xG/npxG/PSxG as-of.

Se ejecuta fuera del hot refresh. Construye predicciones walk-forward del motor
base, Elo y DC, alinea el archivo avanzado por ``available_at < kickoff`` y exige
que el challenger gane en la MISMA cola a todos los baselines requeridos.

El informe es observabilidad/model governance. Nunca modifica dashboard.probs ni
publica parámetros de producción.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import warnings

from .advanced_stats import DEFAULT_PATH, load_archive
from .backtest import (
    DixonColesPredictor,
    EloPredictor,
    HybridDixonColesPredictor,
    fit_walk_forward_advanced_residual,
    walk_forward,
)
from .config import DATA_DIR, LEAGUE_META, settings
from .ingest.football_data_uk import FootballDataUKClient
from .normalize import canonical_team
from .pipeline import fixtures_to_matches, get_fixtures
from .value.odds import remove_vig

OUTPUT = Path(DATA_DIR) / "advanced_outcome_challenger.json"
LEAGUES = ("laliga", "segunda", "champions")


def _canon(name: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return canonical_team(str(name or ""))


def _fair_1x2(prices: dict | None) -> dict[str, float] | None:
    if not isinstance(prices, dict):
        return None
    try:
        odds = [float(prices[key]) for key in ("1", "X", "2")]
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 1.0 for value in odds):
        return None
    fair = remove_vig(odds)
    return dict(zip(("1", "X", "2"), map(float, fair)))


def _closing_index(rows: list[dict]) -> tuple[dict[tuple[str, str], dict], set[tuple[str, str]]]:
    """Indexa solo emparejamientos no ambiguos; nunca fuzzy-match ni sobreescribe."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows or []:
        key = (_canon(row.get("home")), _canon(row.get("away")))
        prices = ((row.get("closing_odds") or {}).get("1x2"))
        fair = _fair_1x2(prices)
        if key[0] and key[1] and fair:
            buckets.setdefault(key, []).append(fair)
    ambiguous = {key for key, values in buckets.items() if len(values) != 1}
    return {key: values[0] for key, values in buckets.items() if len(values) == 1}, ambiguous


def market_baseline_records(base_records: list[dict], closing_rows: list[dict]) -> tuple[list[dict], dict]:
    """Crea baseline no-vig con las mismas claves de records del walk-forward."""
    index, ambiguous = _closing_index(closing_rows)
    out = []
    missing = 0
    for record in base_records:
        key = (_canon(record.get("home")), _canon(record.get("away")))
        fair = index.get(key)
        if not fair:
            missing += 1
            continue
        out.append({**record, "probs": fair, "baseline_source": "football-data.co.uk closing no-vig"})
    return out, {
        "n": len(out),
        "required": len(base_records),
        "complete": len(out) == len(base_records) and bool(out),
        "missing": missing,
        "ambiguous_pairs": len(ambiguous),
        "role": "comparator_only_not_feature",
        "leakage_note": "closing odds are never advanced-model features; comparator only",
    }


def _blocked(status: str, *, league: str, season: int, detail: str | None = None) -> dict:
    return {
        "league": league,
        "season": season,
        "status": status,
        "accepted": False,
        "affects_1x2": False,
        "promotion_status": "manual_future_pr_required",
        "detail": detail,
    }


def build_league_report(
    league: str,
    season: int,
    *,
    archive_path: str | Path = DEFAULT_PATH,
) -> dict:
    """Construye un informe reproducible para una liga y temporada."""
    try:
        tpr = LEAGUE_META.get(league, {}).get("teams_per_round")
        fixtures = get_fixtures(league, season=season)
        try:
            client = FootballDataUKClient()
            stats_rows = client.get_stats(league, season)
        except Exception:
            client = FootballDataUKClient()
            stats_rows = []
        matches = fixtures_to_matches(fixtures, teams_per_round=tpr, stats_rows=stats_rows)
    except Exception as exc:
        return _blocked(
            "blocked_source_error",
            league=league,
            season=season,
            detail=type(exc).__name__,
        )
    if not matches:
        return _blocked("blocked_no_finished_matches", league=league, season=season)

    results = {}
    for name, predictor in {
        "elo": EloPredictor(),
        "dixon_coles": DixonColesPredictor(min_matches=30),
        "hybrid_dixon_coles": HybridDixonColesPredictor(min_matches=30),
    }.items():
        try:
            result = walk_forward(matches, predictor, min_train_rounds=3)
        except Exception:
            continue
        if result.records:
            results[name] = result

    elo = results.get("elo")
    dc = results.get("dixon_coles")
    base = results.get("hybrid_dixon_coles") or dc
    if elo is None or base is None:
        return _blocked(
            "blocked_insufficient_base_predictions",
            league=league,
            season=season,
        )

    archive = load_archive(archive_path)
    extras: dict[str, list[dict]] = {}
    if dc is not None and base is not dc:
        extras["dixon_coles"] = dc.records

    # Mercado no-vig es requisito de promoción, pero jamás feature. Para ligas
    # sin histórico closing compatible se pasa una lista vacía: el gate queda
    # explícitamente bloqueado por cobertura incompleta.
    try:
        closing_rows = client.get_historical_closing_odds(league, season)
    except Exception:
        closing_rows = []
    market_records, market_coverage = market_baseline_records(base.records, closing_rows)
    extras["market_no_vig"] = market_records

    challenger = fit_walk_forward_advanced_residual(
        base.records,
        elo.records,
        archive,
        league=league,
        season=season,
        base_name="hybrid_dixon_coles" if base is not dc else "dixon_coles",
        extra_baseline_records=extras,
    )
    return {
        "league": league,
        "season": season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "archive_path": str(archive_path),
        "archive_snapshots": len(archive.get("snapshots") or []),
        "finished_matches": len(matches),
        "base_prediction_records": len(base.records),
        "market_comparator": market_coverage,
        "challenger": challenger,
        "accepted": bool(challenger.get("accepted")),
        "status": challenger.get("status"),
        "affects_1x2": False,
        "promotion_status": "manual_future_pr_required",
        "governance": {
            "features": "base residual + xG/npxG attack/defence + shrunk goalkeeper PSxG+/-",
            "snapshot_rule": "available_at < kickoff",
            "validation": "chronological tail; simultaneous match-days kept together",
            "gate": "strict improvement in log_loss and RPS vs base, Elo, same-sample residual, DC and no-vig market",
            "production_wiring": False,
        },
    }


def build_report(
    *,
    leagues: tuple[str, ...] = LEAGUES,
    season: int | None = None,
    archive_path: str | Path = DEFAULT_PATH,
) -> dict:
    actual_season = int(season or settings.season)
    reports = {
        league: build_league_report(league, actual_season, archive_path=archive_path)
        for league in leagues
    }
    return {
        "schema": "advanced-outcome-challenger-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": actual_season,
        "affects_1x2": False,
        "reports": reports,
    }


def write_report(payload: dict, path: str | Path = OUTPUT) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2.3 advanced outcome challenger report")
    parser.add_argument("--league", choices=[*LEAGUES, "all"], default="all")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--archive", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    leagues = LEAGUES if args.league == "all" else (args.league,)
    report = build_report(leagues=leagues, season=args.season, archive_path=args.archive)
    path = write_report(report, args.output)
    statuses = {key: value.get("status") for key, value in report["reports"].items()}
    print(json.dumps({"written": str(path), "statuses": statuses, "affects_1x2": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
