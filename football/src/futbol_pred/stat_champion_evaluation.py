"""P3.6a: evaluación independiente del champion estadístico.

Este módulo ejecuta el MISMO gate temporal que usa ``StatsPredictor`` pero fuera
del dashboard. Su salida no participa en el quality gate del feed y nunca cambia
probabilidades, pseudo-xG ni mercados. El objetivo es que siempre exista evidencia
``equipo × estadística × método`` aunque un dashboard candidato sea rechazado.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .ingest.football_data_uk import FootballDataUKClient, MatchStats
from .model.stats_markets import CHAMPION_STATS, validate_regression_champions
from .normalize import canonical_team

SCHEMA = "stat-champion-evaluation-v1"
DEFAULT_LEAGUES = ("laliga", "segunda")
DEFAULT_CURRENT_SEASON = 2026
DEFAULT_HISTORY_SEASONS = 3
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "data-history" / "stat_champion_evaluation.json"


def season_window(current_season: int, history_seasons: int) -> list[int]:
    count = max(1, int(history_seasons))
    current = int(current_season)
    return list(range(current - count + 1, current + 1))


def _match_key(match: MatchStats) -> tuple:
    kickoff = match.kickoff.isoformat() if match.kickoff else ""
    return (
        kickoff,
        canonical_team(match.home_team),
        canonical_team(match.away_team),
    )


def _load_league_history(
    client: FootballDataUKClient,
    league: str,
    seasons: Iterable[int],
) -> tuple[list[MatchStats], list[dict]]:
    rows: list[MatchStats] = []
    audit: list[dict] = []
    seen: set[tuple] = set()
    for season in seasons:
        try:
            batch = client.get_stats(league, int(season), offline=False)
        except Exception as exc:  # red/HTTP: se audita y nunca se rellena con sample
            audit.append({
                "season": int(season),
                "status": "source_error",
                "rows": 0,
                "error_type": type(exc).__name__,
            })
            continue
        kept = 0
        for match in batch:
            key = _match_key(match)
            if key in seen:
                continue
            seen.add(key)
            rows.append(match)
            kept += 1
        audit.append({
            "season": int(season),
            "status": "ok",
            "rows": kept,
        })
    rows.sort(key=lambda match: match.kickoff or datetime.min)
    return rows, audit


def _flatten_team_rows(league: str, validation: dict) -> list[dict]:
    out: list[dict] = []
    by_team = validation.get("by_team") or {}
    for team in sorted(by_team):
        stat_map = by_team.get(team) or {}
        for stat in sorted(stat_map):
            row = stat_map.get(stat) or {}
            methods = {
                "ataque_defensa": {
                    "mae": row.get("default_mae"),
                    "bias": row.get("default_bias"),
                    "gain_pct": 0.0,
                    "passed": row.get("method") == "ataque_defensa",
                }
            }
            for method, candidate in sorted((row.get("candidates") or {}).items()):
                methods[method] = {
                    "mae": candidate.get("mae"),
                    "bias": candidate.get("bias"),
                    "gain_pct": candidate.get("gain_pct"),
                    "bias_gate": candidate.get("bias_gate"),
                    "passed": candidate.get("passed"),
                }
            out.append({
                "league": league,
                "team": team,
                "stat": stat,
                "n_validation": row.get("n"),
                "selected_method": row.get("method") or "ataque_defensa",
                "accepted_challenger": bool(row.get("accepted")),
                "methods": methods,
            })
    return out


def evaluate_league(
    league: str,
    matches: list[MatchStats],
    source_audit: list[dict],
) -> dict:
    validation = validate_regression_champions(matches)
    usable_source_seasons = sum(1 for row in source_audit if row.get("status") == "ok" and row.get("rows", 0) > 0)
    return {
        "league": league,
        "source": "football-data.co.uk",
        "source_seasons": source_audit,
        "source_complete": usable_source_seasons == len(source_audit),
        "n_matches": len(matches),
        "validation": validation,
        "team_stat_rows": _flatten_team_rows(league, validation),
        "affects_pseudo_xg": False,
        "affects_1x2": False,
        "affects_production": False,
    }


def build_report(
    league_matches: dict[str, list[MatchStats]],
    source_audits: dict[str, list[dict]],
    *,
    current_season: int,
    history_seasons: int,
) -> dict:
    leagues: dict[str, dict] = {}
    flat_rows: list[dict] = []
    for league in sorted(league_matches):
        row = evaluate_league(
            league,
            league_matches.get(league) or [],
            source_audits.get(league) or [],
        )
        leagues[league] = row
        flat_rows.extend(row["team_stat_rows"])

    complete = bool(leagues) and all(row.get("source_complete") for row in leagues.values())
    accepted = [
        row for row in flat_rows
        if row.get("accepted_challenger")
    ]
    return {
        "schema": SCHEMA,
        "current_season": int(current_season),
        "history_seasons": int(history_seasons),
        "stats_scope": list(CHAMPION_STATS),
        "leagues": leagues,
        "team_stat_rows": flat_rows,
        "summary": {
            "source_complete": complete,
            "league_count": len(leagues),
            "team_stat_rows": len(flat_rows),
            "accepted_challengers": len(accepted),
            "accepted_by_league": {
                league: sum(1 for row in accepted if row.get("league") == league)
                for league in sorted(leagues)
            },
        },
        "quality_gate_independent": True,
        "automatic_production_promotion": False,
        "affects_pseudo_xg": False,
        "affects_1x2": False,
        "affects_production": False,
    }


def _semantic_payload(report: dict) -> dict:
    return {
        key: deepcopy(value)
        for key, value in report.items()
        if key not in {"generated_at", "semantic_hash"}
    }


def semantic_hash(report: dict) -> str:
    raw = json.dumps(
        _semantic_payload(report),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_report(path: str | Path = DEFAULT_OUTPUT) -> dict | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and raw.get("schema") == SCHEMA else None


def write_report(
    report: dict,
    path: str | Path = DEFAULT_OUTPUT,
    *,
    generated_at: str | None = None,
) -> dict:
    target = Path(path)
    previous = load_report(target)
    digest = semantic_hash(report)
    if previous and previous.get("semantic_hash") == digest:
        return {
            "status": "unchanged",
            "path": str(target),
            "semantic_hash": digest,
            "summary": previous.get("summary") or {},
            "affects_1x2": False,
        }

    # Una caída parcial de la fuente no reemplaza un informe bueno ya persistido.
    complete = bool((report.get("summary") or {}).get("source_complete"))
    if previous and not complete:
        return {
            "status": "source_degraded_preserved_last_good",
            "path": str(target),
            "semantic_hash": previous.get("semantic_hash"),
            "summary": previous.get("summary") or {},
            "affects_1x2": False,
        }

    output = deepcopy(report)
    output["generated_at"] = generated_at or datetime.now(timezone.utc).isoformat()
    output["semantic_hash"] = digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "written",
        "path": str(target),
        "semantic_hash": digest,
        "summary": output.get("summary") or {},
        "affects_1x2": False,
    }


def refresh(
    *,
    current_season: int = DEFAULT_CURRENT_SEASON,
    history_seasons: int = DEFAULT_HISTORY_SEASONS,
    leagues: Iterable[str] = DEFAULT_LEAGUES,
    output: str | Path = DEFAULT_OUTPUT,
    timeout: int = 20,
) -> dict:
    seasons = season_window(current_season, history_seasons)
    client = FootballDataUKClient(timeout=timeout)
    league_matches: dict[str, list[MatchStats]] = {}
    source_audits: dict[str, list[dict]] = {}
    for league in leagues:
        rows, audit = _load_league_history(client, league, seasons)
        league_matches[league] = rows
        source_audits[league] = audit
    report = build_report(
        league_matches,
        source_audits,
        current_season=current_season,
        history_seasons=history_seasons,
    )
    result = write_report(report, output)
    result["source_audits"] = source_audits
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="P3.6a · evaluación independiente del champion estadístico")
    parser.add_argument("--season", type=int, default=DEFAULT_CURRENT_SEASON)
    parser.add_argument("--history-seasons", type=int, default=DEFAULT_HISTORY_SEASONS)
    parser.add_argument("--league", action="append", choices=DEFAULT_LEAGUES)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    result = refresh(
        current_season=args.season,
        history_seasons=args.history_seasons,
        leagues=args.league or DEFAULT_LEAGUES,
        output=args.output,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
