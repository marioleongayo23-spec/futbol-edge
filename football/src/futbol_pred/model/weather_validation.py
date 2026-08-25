"""Gate temporal para promover o bloquear ajustes meteorológicos.

La heurística de clima nunca se valida contra el tiempo final observado como si
hubiese sido conocido antes del partido. Cada fila meteorológica debe proceder de
un forecast histórico con lead time fijo (por defecto T-24h) y declarar
``leakage_safe=True``.

El gate compara, estadística a estadística, el predictor de equipos puro contra
el mismo predictor multiplicado por la heurística meteorológica. Solo se evalúan
partidos donde la heurística realmente cambiaría esa métrica; un gran conjunto de
partidos neutrales no puede maquillar el MAE. La promoción exige muestra activa
mínima y MAE estrictamente menor sobre una cola temporal no vista.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

import numpy as np

from ..ingest.football_data_uk import MatchStats
from ..normalize import canonical_team
from ..weather_effects import weather_multipliers
from .stats_markets import StatsPredictor

WEATHER_STATS = ("goals", "shots", "sot", "fouls", "yellows", "reds")
MIN_HISTORY = 80
MIN_VALIDATION = 20
MIN_ACTIVE_VALIDATION = 12

_FACTOR_KEY = {
    "goals": "goals",
    "shots": "shots",
    "sot": "shots",
    "fouls": "fouls",
    "yellows": "cards",
    "reds": "cards",
}


def weather_match_key(home: str, away: str, kickoff: datetime | None) -> str:
    date = kickoff.date().isoformat() if isinstance(kickoff, datetime) else ""
    return "|".join((canonical_team(home), canonical_team(away), date))


def _dated(matches: list[MatchStats]) -> list[MatchStats]:
    return sorted(
        (row for row in matches if isinstance(row.kickoff, datetime)),
        key=lambda row: row.kickoff,
    )


def _weather_for(match: MatchStats, archive: Mapping[str, dict]) -> dict | None:
    row = archive.get(weather_match_key(match.home_team, match.away_team, match.kickoff))
    if not isinstance(row, dict):
        return None
    weather = row.get("weather_t24") if isinstance(row.get("weather_t24"), dict) else row
    if not isinstance(weather, dict):
        return None
    if weather.get("leakage_safe") is not True:
        return None
    try:
        lead = int(weather.get("lead_hours"))
    except (TypeError, ValueError):
        return None
    return weather if lead >= 24 else None


def validate_weather_adjustment(
    matches: list[MatchStats],
    weather_archive: Mapping[str, dict],
    *,
    validation_fraction: float = 0.25,
) -> dict:
    """Compara baseline vs clima en una cola cronológica nunca entrenada."""

    dated = _dated(matches)
    if len(dated) < MIN_HISTORY:
        return {
            "method": "weather-t24-time-holdout",
            "status": "blocked_insufficient_dated_sample",
            "accepted": False,
            "accepted_stats": [],
            "n": len(dated),
            "minimum_required": MIN_HISTORY,
            "validation": {},
            "gate": "strictly_lower_mae_on_active_weather_matches",
        }

    split = max(
        MIN_HISTORY - MIN_VALIDATION,
        min(len(dated) - MIN_VALIDATION, round(len(dated) * (1.0 - validation_fraction))),
    )
    train, validation = dated[:split], dated[split:]
    baseline = StatsPredictor().fit(
        train,
        temporal_stats=set(),
        auto_temporal=False,
        fit_pseudo_xg=False,
    )

    report: dict[str, dict] = {}
    accepted_stats: list[str] = []
    covered = sum(1 for match in validation if _weather_for(match, weather_archive))

    for stat in WEATHER_STATS:
        base_errors: list[float] = []
        weather_errors: list[float] = []
        active_examples: list[dict] = []
        factor_key = _FACTOR_KEY[stat]
        for match in validation:
            weather = _weather_for(match, weather_archive)
            actual = match.stats.get(stat)
            if not weather or actual is None:
                continue
            predicted = baseline.predict_fixture(match.home_team, match.away_team).get(stat)
            if not predicted:
                continue
            factors, _ = weather_multipliers(weather)
            factor = float(factors[factor_key])
            # El gate debe medir el efecto del clima, no diluirlo con partidos
            # donde la heurística no toca nada.
            if abs(factor - 1.0) < 1e-9:
                continue
            actual_total = float(actual[0]) + float(actual[1])
            baseline_total = float(predicted["total"])
            challenger_total = baseline_total * factor
            base_errors.append(abs(baseline_total - actual_total))
            weather_errors.append(abs(challenger_total - actual_total))
            if len(active_examples) < 5:
                active_examples.append({
                    "key": weather_match_key(match.home_team, match.away_team, match.kickoff),
                    "factor": round(factor, 4),
                })

        n = len(base_errors)
        if not n:
            report[stat] = {
                "n_active": 0,
                "accepted": False,
                "reason": "no_active_weather_examples",
            }
            continue
        baseline_mae = float(np.mean(base_errors))
        weather_mae = float(np.mean(weather_errors))
        improved = n >= MIN_ACTIVE_VALIDATION and weather_mae < baseline_mae
        report[stat] = {
            "n_active": n,
            "minimum_active_required": MIN_ACTIVE_VALIDATION,
            "baseline_mae": round(baseline_mae, 4),
            "weather_mae": round(weather_mae, 4),
            "delta": round(weather_mae - baseline_mae, 4),
            "relative_improvement_pct": round(
                100.0 * (baseline_mae - weather_mae) / baseline_mae, 2
            ) if baseline_mae > 0 else None,
            "accepted": improved,
            "sample_examples": active_examples,
        }
        if improved:
            accepted_stats.append(stat)

    return {
        "method": "weather-t24-time-holdout",
        "status": "accepted_partial" if accepted_stats else "blocked_by_gate",
        "accepted": bool(accepted_stats),
        "accepted_stats": accepted_stats,
        "n_train": len(train),
        "n_validation": len(validation),
        "weather_coverage_validation": covered,
        "weather_coverage_pct": round(100 * covered / len(validation), 1) if validation else 0.0,
        "forecast_contract": "Open-Meteo Previous Runs · lead_hours>=24 · leakage_safe=true",
        "gate": "strictly_lower_mae_on_active_weather_matches",
        "validation": report,
    }


def accepted_weather_factors(report: dict | None) -> dict[str, bool]:
    """Convierte el informe por stat en switches usados por producción."""

    accepted = set((report or {}).get("accepted_stats") or [])
    return {
        "goals": "goals" in accepted,
        "shots": bool({"shots", "sot"} & accepted),
        "fouls": "fouls" in accepted,
        "cards": bool({"yellows", "reds"} & accepted),
    }
