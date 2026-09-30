"""P3.5: challengers estadísticos en sombra, sin autoridad de producción.

Los challengers se construyen SOLO al capturar un snapshot prepartido. Aprenden
exclusivamente del archivo acumulativo ``truth_evaluation.json`` ya publicado,
por lo que una observación posterior al saque inicial nunca puede modificar un
snapshot histórico. En esta fase se limita a disciplina (faltas/amarillas), que
no alimenta pseudo-xG ni el 1X2.

El primer challenger corrige de forma conservadora el sesgo observado del
pronóstico publicado. La corrección se contrae hacia cero y se limita por lado;
sirve para generar evidencia prospectiva, no para alterar el feed de serving.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

SCHEMA = "stat-shadow-v1"
SHADOW_STATS = ("fouls", "yellows")
SHADOW_METHOD = "bias_shrunk_v1"
MIN_GLOBAL_SAMPLE = 20
MIN_LEAGUE_SAMPLE = 12
SHRINKAGE_PRIOR_N = 40.0
MAX_RELATIVE_CORRECTION = 0.20

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVALUATION = REPO_ROOT / "data-history" / "truth_evaluation.json"

_LEAGUE_MAP = {
    "LaLiga": "laliga",
    "LaLiga Hypermotion": "segunda",
    "Champions League": "champions",
    "laliga": "laliga",
    "segunda": "segunda",
    "champions": "champions",
}


def _num(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _pair(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    home, away = _num(row.get("home")), _num(row.get("away"))
    if home is None or away is None or home < 0 or away < 0:
        return None
    return {"home": home, "away": away, "total": home + away}


def _load_evaluation(path: str | Path = DEFAULT_EVALUATION) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema") != "truth-evaluation-v1":
        return {}
    return raw


def _metrics_for(summary: dict, league: str, stat: str) -> tuple[dict | None, str]:
    league_row = (((summary.get("by_league") or {}).get(league) or {}).get(stat))
    if isinstance(league_row, dict) and int(league_row.get("n") or 0) >= MIN_LEAGUE_SAMPLE:
        return league_row, "league"
    global_row = ((summary.get("by_stat") or {}).get(stat))
    if isinstance(global_row, dict) and int(global_row.get("n") or 0) >= MIN_GLOBAL_SAMPLE:
        return global_row, "global"
    return None, "insufficient"


def _bounded_correction(predicted: float, raw_correction: float) -> float:
    cap = max(0.25, abs(predicted) * MAX_RELATIVE_CORRECTION)
    return max(-cap, min(cap, raw_correction))


def build_stat_shadow(
    match: dict,
    *,
    evaluation: dict | None = None,
    evaluation_path: str | Path = DEFAULT_EVALUATION,
) -> dict | None:
    """Construye baseline + challenger de sesgo para un snapshot futuro.

    ``match`` no se modifica. Si la muestra histórica todavía no alcanza el
    mínimo, devuelve ``None``: no se fabrica evidencia ni se rellena con priors.
    """

    stats = match.get("stats") or {}
    if not isinstance(stats, dict):
        return None
    archive = evaluation if isinstance(evaluation, dict) else _load_evaluation(evaluation_path)
    if archive.get("schema") != "truth-evaluation-v1":
        return None
    summary = archive.get("summary") or {}
    league = _LEAGUE_MAP.get(str(match.get("league") or ""), str(match.get("league") or "").casefold())
    out_stats: dict[str, dict] = {}

    for stat in SHADOW_STATS:
        baseline = _pair(stats.get(stat))
        metrics, scope = _metrics_for(summary, league, stat)
        if baseline is None or metrics is None:
            continue
        n = int(metrics.get("n") or 0)
        bias = metrics.get("bias_predicted_minus_actual") or {}
        bias_home, bias_away = _num(bias.get("home")), _num(bias.get("away"))
        if bias_home is None or bias_away is None or n <= 0:
            continue

        shrinkage = n / (n + SHRINKAGE_PRIOR_N)
        corr_home = _bounded_correction(baseline["home"], bias_home * shrinkage)
        corr_away = _bounded_correction(baseline["away"], bias_away * shrinkage)
        home = max(0.0, baseline["home"] - corr_home)
        away = max(0.0, baseline["away"] - corr_away)
        challenger = {
            "home": round(home, 4),
            "away": round(away, 4),
            "total": round(home + away, 4),
        }
        out_stats[stat] = {
            "published": {key: round(float(baseline[key]), 4) for key in ("home", "away", "total")},
            SHADOW_METHOD: challenger,
            "training": {
                "source": "truth_evaluation_v1_prior_only",
                "evaluation_updated_at": archive.get("updated_at"),
                "scope": scope,
                "league": league,
                "n": n,
                "observed_bias": {
                    "home": round(bias_home, 4),
                    "away": round(bias_away, 4),
                },
                "shrinkage": round(shrinkage, 6),
                "max_relative_correction": MAX_RELATIVE_CORRECTION,
            },
        }

    if not out_stats:
        return None
    return {
        "schema": SCHEMA,
        "stats": out_stats,
        "affects_production": False,
        "affects_1x2": False,
        "automatic_production_promotion": False,
        "gate": "prospective_truth_only + evaluation_ready_n>=80 + challenger_mae_gain",
    }
