"""Histórico causal de mercado y challenger de movimiento 1X2.

La regla central es temporal: este módulo solo usa snapshots capturados antes del
kickoff. Las cuotas históricas de cierre de football-data.co.uk NO se convierten
en snapshots T-24/T-6 ficticios. Pueden servir para investigación separada, pero
nunca para entrenar este challenger de producción.

Este módulo forma parte del hot-refresh ligero. Por eso sus métricas probabilísticas
se implementan con stdlib y NO importan el paquete de backtest/Dixon-Coles/NumPy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math

from .prediction_snapshots import latest_pre_match_snapshot

SIGNS = ("1", "X", "2")
SCHEMA = "market-snapshot-v1"
POLICY_SCHEMA = "market-movement-calibration-v1"
MAX_HISTORY = 32
MIN_SAMPLE = 60
MIN_VALIDATION = 20
BETA_GRID = (-3.0, -2.0, -1.5, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _normalise(values) -> dict[str, float] | None:
    if isinstance(values, dict):
        raw = [values.get(sign) for sign in SIGNS]
    elif isinstance(values, (list, tuple)) and len(values) == 3:
        raw = list(values)
    else:
        return None
    try:
        nums = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value < 0 for value in nums):
        return None
    # El feed usa porcentajes en ``probs`` y fracciones en ``fair``.
    if sum(nums) > 2.0:
        nums = [value / 100.0 for value in nums]
    total = sum(nums)
    if total <= 0:
        return None
    nums = [max(1e-9, value / total) for value in nums]
    total = sum(nums)
    return {sign: nums[index] / total for index, sign in enumerate(SIGNS)}


def _aggregate(predictions: list[tuple[dict[str, float], str]]) -> dict[str, float]:
    """Mismas métricas 1X2 del backtest, pero sin dependencias pesadas."""
    if not predictions:
        return {"n": 0}
    n = len(predictions)
    log_total = brier_total = rps_total = accuracy_total = 0.0
    for probs, actual in predictions:
        log_total += -math.log(min(1.0 - 1e-12, max(1e-12, probs[actual])))
        brier_total += sum(
            (probs[sign] - (1.0 if sign == actual else 0.0)) ** 2
            for sign in SIGNS
        )
        cum_p = cum_o = score = 0.0
        for sign in SIGNS[:-1]:
            cum_p += probs[sign]
            cum_o += 1.0 if sign == actual else 0.0
            score += (cum_p - cum_o) ** 2
        rps_total += score / (len(SIGNS) - 1)
        accuracy_total += 1.0 if max(SIGNS, key=lambda sign: probs[sign]) == actual else 0.0
    return {
        "n": n,
        "log_loss": log_total / n,
        "brier": brier_total / n,
        "rps": rps_total / n,
        "accuracy": accuracy_total / n,
    }


def _horizon_bucket(minutes_to_kickoff: float) -> str:
    if minutes_to_kickoff > 24 * 60:
        return "T-24h+"
    if minutes_to_kickoff > 12 * 60:
        return "T-24h"
    if minutes_to_kickoff > 6 * 60:
        return "T-12h"
    if minutes_to_kickoff > 3 * 60:
        return "T-6h"
    if minutes_to_kickoff > 90:
        return "T-3h"
    if minutes_to_kickoff > 60:
        return "T-90"
    if minutes_to_kickoff > 30:
        return "T-60"
    return "T-30"


def build_market_snapshot(
    *,
    kickoff,
    captured_at,
    odds_1x2: dict,
    fair_1x2: dict,
    provider: str,
    source_updated_at=None,
) -> dict | None:
    kickoff_dt = _parse(kickoff)
    captured_dt = _parse(captured_at)
    fair = _normalise(fair_1x2)
    if kickoff_dt is None or captured_dt is None or fair is None or captured_dt >= kickoff_dt:
        return None
    try:
        odds = {sign: round(float(odds_1x2[sign]), 4) for sign in SIGNS}
    except (KeyError, TypeError, ValueError):
        return None
    minutes = (kickoff_dt - captured_dt).total_seconds() / 60.0
    return {
        "schema": SCHEMA,
        "captured_at": captured_dt.isoformat(),
        "source_updated_at": str(source_updated_at or captured_dt.isoformat()),
        "minutes_to_kickoff": round(minutes, 1),
        "horizon": _horizon_bucket(minutes),
        "provider": str(provider or "unknown"),
        "odds_1x2": odds,
        "fair_1x2": {sign: round(fair[sign], 6) for sign in SIGNS},
    }


def append_market_snapshot(match: dict, snapshot: dict | None, *, max_history: int = MAX_HISTORY) -> bool:
    """Añade una observación solo si aporta tiempo/horizonte o movimiento material.

    Evita guardar cada poll idéntico de 5 minutos. Se conserva una observación al
    cambiar de bucket, cada hora como máximo, o cuando alguna fair se mueve >=0.2pp.
    """
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
        return False
    history = [
        dict(item) for item in (match.get("market_history") or [])
        if isinstance(item, dict) and item.get("schema") == SCHEMA
    ]
    history.sort(key=lambda item: str(item.get("captured_at") or ""))
    if history:
        last = history[-1]
        current_dt, last_dt = _parse(snapshot.get("captured_at")), _parse(last.get("captured_at"))
        current_fair, last_fair = _normalise(snapshot.get("fair_1x2")), _normalise(last.get("fair_1x2"))
        delta = max(
            abs(current_fair[sign] - last_fair[sign]) for sign in SIGNS
        ) if current_fair and last_fair else 1.0
        elapsed = (
            (current_dt - last_dt).total_seconds() / 60.0
            if current_dt is not None and last_dt is not None else 9999.0
        )
        same_source_tick = (
            snapshot.get("source_updated_at") == last.get("source_updated_at")
            and current_fair == last_fair
        )
        new_horizon = snapshot.get("horizon") != last.get("horizon")
        if same_source_tick or (not new_horizon and delta < 0.002 and elapsed < 60):
            match["market_history"] = history[-max_history:]
            return False
    history.append(dict(snapshot))
    history.sort(key=lambda item: str(item.get("captured_at") or ""))
    match["market_history"] = history[-max(2, int(max_history)):]
    return True


def movement_summary(history: list[dict] | None, *, cutoff=None, kickoff=None) -> dict | None:
    cutoff_dt = _parse(cutoff) if cutoff is not None else None
    kickoff_dt = _parse(kickoff) if kickoff is not None else None
    rows = []
    for item in history or []:
        if not isinstance(item, dict) or item.get("schema") != SCHEMA:
            continue
        captured = _parse(item.get("captured_at"))
        fair = _normalise(item.get("fair_1x2"))
        if captured is None or fair is None:
            continue
        if cutoff_dt is not None and captured > cutoff_dt:
            continue
        if kickoff_dt is not None and captured >= kickoff_dt:
            continue
        rows.append((captured, item, fair))
    rows.sort(key=lambda row: row[0])
    if len(rows) < 2:
        return None
    first_dt, first, opening = rows[0]
    last_dt, last, latest = rows[-1]
    if first.get("provider") != last.get("provider"):
        return None
    elapsed_hours = max(1 / 60, (last_dt - first_dt).total_seconds() / 3600.0)
    delta = {sign: latest[sign] - opening[sign] for sign in SIGNS}
    return {
        "schema": "market-movement-v1",
        "provider": first.get("provider"),
        "n_snapshots": len(rows),
        "from": first_dt.isoformat(),
        "to": last_dt.isoformat(),
        "from_minutes_to_kickoff": first.get("minutes_to_kickoff"),
        "to_minutes_to_kickoff": last.get("minutes_to_kickoff"),
        "opening_fair": {sign: round(opening[sign], 6) for sign in SIGNS},
        "current_fair": {sign: round(latest[sign], 6) for sign in SIGNS},
        "delta_pp": {sign: round(100.0 * delta[sign], 3) for sign in SIGNS},
        "velocity_pp_per_hour": {
            sign: round(100.0 * delta[sign] / elapsed_hours, 4) for sign in SIGNS
        },
        "elapsed_hours": round(elapsed_hours, 3),
    }


def apply_movement_policy(base_probs, movement: dict | None, policy: dict | None) -> dict[str, float] | None:
    base = _normalise(base_probs)
    if base is None:
        return None
    if not isinstance(policy, dict) or not policy.get("accepted") or policy.get("schema") != POLICY_SCHEMA:
        return base
    if not isinstance(movement, dict):
        return base
    try:
        beta = float((policy.get("production") or {})["beta"])
        delta = {sign: float((movement.get("delta_pp") or {})[sign]) / 100.0 for sign in SIGNS}
    except (KeyError, TypeError, ValueError):
        return base
    logits = {sign: math.log(max(1e-9, base[sign])) + beta * delta[sign] for sign in SIGNS}
    peak = max(logits.values())
    exp = {sign: math.exp(logits[sign] - peak) for sign in SIGNS}
    total = sum(exp.values()) or 1.0
    return {sign: exp[sign] / total for sign in SIGNS}


def _actual(match: dict) -> str | None:
    result = match.get("result")
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        return None
    try:
        home, away = int(result[0]), int(result[1])
    except (TypeError, ValueError):
        return None
    return "1" if home > away else "X" if home == away else "2"


def _sample(match: dict) -> dict | None:
    actual = _actual(match)
    snapshot = latest_pre_match_snapshot(match)
    if actual is None or not isinstance(snapshot, dict):
        return None
    generated_at = snapshot.get("generated_at")
    movement = movement_summary(
        match.get("market_history"),
        cutoff=generated_at,
        kickoff=match.get("kickoff"),
    )
    prior_adjustment = snapshot.get("market_movement_adjustment")
    base_source = (
        prior_adjustment.get("before")
        if isinstance(prior_adjustment, dict) and isinstance(prior_adjustment.get("before"), list)
        else snapshot.get("probs")
    )
    base = _normalise(base_source)
    kickoff = _parse(match.get("kickoff"))
    if movement is None or base is None or kickoff is None:
        return None
    return {
        "kickoff": kickoff,
        "actual": actual,
        "base": base,
        "movement": movement,
    }


def _candidate(sample: dict, beta: float) -> dict[str, float]:
    policy = {"schema": POLICY_SCHEMA, "accepted": True, "production": {"beta": beta}}
    return apply_movement_policy(sample["base"], sample["movement"], policy) or sample["base"]


def _fit_beta(samples: list[dict]) -> float:
    best_beta = 0.0
    best_score = float("inf")
    for beta in BETA_GRID:
        metrics = _aggregate([(_candidate(sample, beta), sample["actual"]) for sample in samples])
        score = float(metrics.get("log_loss", 99.0)) + float(metrics.get("rps", 99.0))
        if score < best_score - 1e-12:
            best_score, best_beta = score, beta
    return float(best_beta)


def learn_market_movement_challenger(matches: list[dict], *, min_sample: int = MIN_SAMPLE) -> dict:
    """Aprende beta de movimiento con split cronológico y gate log-loss + RPS.

    Solo entran partidos que tengan >=2 snapshots LIVE reales anteriores al
    snapshot de predicción usado como baseline. No existe fallback a closing odds.
    """
    samples = [sample for match in matches if (sample := _sample(match)) is not None]
    samples.sort(key=lambda sample: sample["kickoff"])
    minimum = max(int(min_sample), MIN_VALIDATION + 20)
    if len(samples) < minimum:
        return {
            "schema": POLICY_SCHEMA,
            "accepted": False,
            "status": "blocked_insufficient_live_snapshots",
            "n": len(samples),
            "minimum_required": minimum,
            "source_policy": "live_prematch_snapshots_only_no_closing_backfill",
        }

    split = max(20, min(len(samples) - MIN_VALIDATION, round(len(samples) * 0.70)))
    # No partimos un mismo día entre train y validación.
    boundary_day = samples[split]["kickoff"].date() if split < len(samples) else None
    while split > 20 and boundary_day and samples[split - 1]["kickoff"].date() == boundary_day:
        split -= 1
    train, validation = samples[:split], samples[split:]
    if len(validation) < MIN_VALIDATION:
        return {
            "schema": POLICY_SCHEMA,
            "accepted": False,
            "status": "blocked_insufficient_validation",
            "n_train": len(train),
            "n_validation": len(validation),
        }

    beta = _fit_beta(train)
    baseline_metrics = _aggregate([(sample["base"], sample["actual"]) for sample in validation])
    candidate_metrics = _aggregate([(_candidate(sample, beta), sample["actual"]) for sample in validation])
    accepted = (
        beta != 0.0
        and candidate_metrics.get("log_loss", 99) < baseline_metrics.get("log_loss", 99)
        and candidate_metrics.get("rps", 99) < baseline_metrics.get("rps", 99)
    )
    production_beta = _fit_beta(samples) if accepted else 0.0
    return {
        "schema": POLICY_SCHEMA,
        "accepted": bool(accepted),
        "status": "accepted" if accepted else "blocked_by_gate",
        "n_train": len(train),
        "n_validation": len(validation),
        "train_end": train[-1]["kickoff"].isoformat(),
        "validation_start": validation[0]["kickoff"].isoformat(),
        "validation": {
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "beta": beta,
        },
        "gate": "candidate_strictly_better_log_loss_and_rps_same_temporal_tail",
        "production": {"beta": production_beta},
        "source_policy": "live_prematch_snapshots_only_no_closing_backfill",
    }
