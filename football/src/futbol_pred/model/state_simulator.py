"""Simulador Monte Carlo de estados, separado del predictor de producción."""

from __future__ import annotations

import hashlib

import numpy as np


def _pace_multiplier(temperature_c: float | None) -> float:
    if temperature_c is None:
        return 1.0
    if temperature_c >= 35:
        return 0.87
    if temperature_c >= 32:
        return 0.92
    if temperature_c >= 29:
        return 0.96
    return 1.0


def simulate_match_states(
    home_xg: float,
    away_xg: float,
    *,
    seed: str,
    temperature_c: float | None = None,
    expected_yellows: float | None = None,
    simulations: int = 4000,
) -> dict:
    """Simula tramos de cinco minutos con marcador, calor, fatiga y expulsión.

    Es análisis de escenarios: no sustituye las probabilidades publicadas hasta
    que sus resultados históricos superen el mismo gate que el resto de modelos.
    """
    n = max(500, min(20000, int(simulations)))
    numeric_seed = int.from_bytes(hashlib.sha256(str(seed).encode()).digest()[:8], "big")
    rng = np.random.default_rng(numeric_seed)
    home = np.zeros(n, dtype=np.int16)
    away = np.zeros(n, dtype=np.int16)
    home_trailed = np.zeros(n, dtype=bool)
    away_trailed = np.zeros(n, dtype=bool)
    pace = _pace_multiplier(temperature_c)
    red_probability = min(0.16, 0.025 + 0.008 * max(0.0, float(expected_yellows or 0)))
    red_home = np.where(rng.random(n) < red_probability / 2, rng.integers(3, 18, n), 99)
    red_away = np.where(rng.random(n) < red_probability / 2, rng.integers(3, 18, n), 99)

    for segment in range(18):
        goal_diff = home - away
        late = segment >= 14
        home_state = np.where(goal_diff < 0, 1.18 if late else 1.10, np.where(goal_diff > 0, 0.88 if late else 0.94, 1.0))
        away_state = np.where(goal_diff > 0, 1.18 if late else 1.10, np.where(goal_diff < 0, 0.88 if late else 0.94, 1.0))
        # Con diez: baja la producción propia y aumenta la del rival.
        home_red = red_home <= segment
        away_red = red_away <= segment
        home_rate = home_xg / 18 * pace * home_state * np.where(home_red, 0.72, 1.0) * np.where(away_red, 1.12, 1.0)
        away_rate = away_xg / 18 * pace * away_state * np.where(away_red, 0.72, 1.0) * np.where(home_red, 1.12, 1.0)
        home += rng.poisson(np.maximum(0, home_rate))
        away += rng.poisson(np.maximum(0, away_rate))
        home_trailed |= home < away
        away_trailed |= away < home

    totals = home + away
    neutral_total = max(0.0, float(home_xg) + float(away_xg))

    # Desglose que pedía el simulador: marcadores exactos simulados y márgenes de
    # victoria. Se obtienen del MISMO recuento Monte Carlo, sin otra hipótesis.
    from collections import Counter

    pairs = Counter(zip(home.tolist(), away.tolist()))
    exact_scores = [
        {"score": f"{h}-{a}", "probability": round(count / n, 4)}
        for (h, a), count in pairs.most_common(8)
    ]
    diff = home - away
    winning_margins = {
        "home_by_1": round(float(np.mean(diff == 1)), 4),
        "home_by_2": round(float(np.mean(diff == 2)), 4),
        "home_by_3plus": round(float(np.mean(diff >= 3)), 4),
        "draw": round(float(np.mean(diff == 0)), 4),
        "away_by_1": round(float(np.mean(diff == -1)), 4),
        "away_by_2": round(float(np.mean(diff == -2)), 4),
        "away_by_3plus": round(float(np.mean(diff <= -3)), 4),
    }
    return {
        "method": "monte_carlo_5min_game_state_v1",
        "status": "scenario_only_not_in_1x2",
        "simulations": n,
        "probabilities": {
            "1": round(float(np.mean(home > away)), 4),
            "X": round(float(np.mean(home == away)), 4),
            "2": round(float(np.mean(home < away)), 4),
        },
        "expected_total_goals": round(float(np.mean(totals)), 2),
        "over_2_5": round(float(np.mean(totals >= 3)), 4),
        "btts": round(float(np.mean((home > 0) & (away > 0))), 4),
        "clean_sheet": {
            "home": round(float(np.mean(away == 0)), 4),
            "away": round(float(np.mean(home == 0)), 4),
        },
        "comeback_win": {
            "home": round(float(np.mean(home_trailed & (home > away))), 4),
            "away": round(float(np.mean(away_trailed & (away > home))), 4),
        },
        "total_goals_range_80": [
            int(np.quantile(totals, 0.10, method="lower")),
            int(np.quantile(totals, 0.90, method="higher")),
        ],
        "exact_scores": exact_scores,
        "winning_margins": winning_margins,
        "assumptions": {
            "temperature_c": temperature_c,
            "pace_multiplier": pace,
            "estimated_goal_delta_vs_neutral": round(neutral_total * (pace - 1), 2),
            "red_card_probability": round(red_probability, 3),
            "state_effects": "el equipo que pierde arriesga más; el que gana reduce ritmo, sobre todo desde el 70'",
        },
    }
