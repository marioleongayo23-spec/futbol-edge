"""Evaluación rolling-origin por jornada sobre predicciones ya walk-forward.

Este módulo NO vuelve a entrenar modelos ni crea un segundo backtest. Consume los
``records`` causales que ya produce :func:`walk_forward` y resume cómo evoluciona
la calidad probabilística jornada a jornada.

La señal de estabilidad es observabilidad, no un gate de promoción: primero
medimos degradación reciente y después, con histórico suficiente, podremos usarla
como condición adicional sin cambiar silenciosamente el campeón.
"""

from __future__ import annotations

from collections import OrderedDict
from statistics import pstdev

from .metrics import aggregate

DEFAULT_TRAILING_ROUNDS = 5
DEGRADATION_TOLERANCE = 0.10


def _record_key(record: dict) -> tuple:
    return (
        tuple(record.get("round") or ()),
        record.get("home"),
        record.get("away"),
        record.get("actual"),
    )


def _round_key(record: dict) -> tuple:
    value = record.get("round")
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


def _round_label(key: tuple) -> str:
    # El último elemento es matchday en el contrato actual. Mantenemos el resto
    # para competiciones por fases donde el número se repite.
    if not key:
        return "sin-jornada"
    matchday = key[-1]
    stage = key[1] if len(key) > 1 else None
    if matchday is not None:
        return f"{stage or 'REGULAR'} · J{matchday}"
    return " · ".join(str(value) for value in key if value is not None) or "sin-jornada"


def _ordered_groups(records: list[dict]) -> list[tuple[tuple, list[dict]]]:
    valid = [
        record for record in records
        if isinstance(record, dict) and record.get("probs") and record.get("actual")
    ]
    valid.sort(key=lambda record: (
        float(record["kickoff"]) if isinstance(record.get("kickoff"), (int, float)) else float("inf"),
        _round_key(record),
        str(record.get("home") or ""),
    ))
    grouped: OrderedDict[tuple, list[dict]] = OrderedDict()
    for record in valid:
        grouped.setdefault(_round_key(record), []).append(record)
    return list(grouped.items())


def _predictions(records: list[dict]) -> list[tuple[dict, str]]:
    return [(record["probs"], record["actual"]) for record in records]


def _rounded(metrics: dict) -> dict:
    return {
        key: (round(value, 5) if isinstance(value, float) else value)
        for key, value in metrics.items()
    }


def _degradation_status(cumulative: dict, recent: dict) -> tuple[str, dict]:
    deltas: dict[str, float | None] = {}
    worse = 0
    for metric in ("log_loss", "rps"):
        whole = cumulative.get(metric)
        tail = recent.get(metric)
        if not isinstance(whole, (int, float)) or not isinstance(tail, (int, float)) or whole <= 0:
            deltas[metric] = None
            continue
        delta = (tail / whole) - 1.0
        deltas[metric] = round(delta, 5)
        if delta > DEGRADATION_TOLERANCE:
            worse += 1
    status = "degrading" if worse == 2 else "watch" if worse == 1 else "stable"
    return status, deltas


def rolling_origin_report(
    records: list[dict],
    *,
    trailing_rounds: int = DEFAULT_TRAILING_ROUNDS,
) -> dict:
    """Resume métricas por jornada, acumuladas y en ventana reciente.

    ``records`` deben proceder del mismo walk-forward; no se reconstruyen cortes
    ni se consulta ninguna fuente externa aquí.
    """
    groups = _ordered_groups(records)
    if not groups:
        return {
            "method": "rolling-origin-by-round-v1",
            "n_rounds": 0,
            "n_predictions": 0,
            "rounds": [],
            "stability": {"status": "insufficient_sample"},
        }

    trailing_rounds = max(1, int(trailing_rounds))
    cumulative_records: list[dict] = []
    round_rows: list[dict] = []
    round_metric_values = {"log_loss": [], "rps": []}

    for index, (key, group) in enumerate(groups):
        cumulative_records.extend(group)
        tail_groups = groups[max(0, index - trailing_rounds + 1): index + 1]
        tail_records = [record for _round, rows in tail_groups for record in rows]
        current_metrics = aggregate(_predictions(group))
        cumulative_metrics = aggregate(_predictions(cumulative_records))
        recent_metrics = aggregate(_predictions(tail_records))
        for metric in round_metric_values:
            value = current_metrics.get(metric)
            if isinstance(value, (int, float)):
                round_metric_values[metric].append(float(value))
        round_rows.append({
            "round": list(key),
            "label": _round_label(key),
            "n": len(group),
            "metrics": _rounded(current_metrics),
            "cumulative": _rounded(cumulative_metrics),
            "trailing": {
                "window_rounds": min(trailing_rounds, index + 1),
                **_rounded(recent_metrics),
            },
        })

    cumulative = aggregate(_predictions(cumulative_records))
    recent_groups = groups[-trailing_rounds:]
    recent_records = [record for _round, rows in recent_groups for record in rows]
    recent = aggregate(_predictions(recent_records))
    status, deltas = _degradation_status(cumulative, recent)
    return {
        "method": "rolling-origin-by-round-v1",
        "n_rounds": len(groups),
        "n_predictions": len(cumulative_records),
        "trailing_rounds": min(trailing_rounds, len(groups)),
        "rounds": round_rows,
        "latest": round_rows[-1],
        "cumulative": _rounded(cumulative),
        "recent": _rounded(recent),
        "stability": {
            "status": status,
            "rule": "recent_log_loss_and_rps_vs_cumulative_10pct_tolerance",
            "tolerance": DEGRADATION_TOLERANCE,
            "recent_vs_cumulative_delta": deltas,
            "round_log_loss_std": round(pstdev(round_metric_values["log_loss"]), 5)
                if len(round_metric_values["log_loss"]) >= 2 else 0.0,
            "round_rps_std": round(pstdev(round_metric_values["rps"]), 5)
                if len(round_metric_values["rps"]) >= 2 else 0.0,
        },
    }


def paired_rolling_comparison(
    candidate_records: list[dict],
    baseline_records: list[dict],
    *,
    trailing_rounds: int = DEFAULT_TRAILING_ROUNDS,
) -> dict:
    """Compara candidato y baseline sobre exactamente los mismos partidos.

    La comparación por jornada exige que ambos tengan la misma observación. No se
    rellenan huecos ni se compara una muestra distinta para favorecer a ninguno.
    """
    baseline_by_key = {_record_key(record): record for record in baseline_records}
    candidate: list[dict] = []
    baseline: list[dict] = []
    for record in candidate_records:
        other = baseline_by_key.get(_record_key(record))
        if not other or not record.get("probs") or not other.get("probs"):
            continue
        candidate.append(record)
        baseline.append(other)

    candidate_report = rolling_origin_report(candidate, trailing_rounds=trailing_rounds)
    baseline_report = rolling_origin_report(baseline, trailing_rounds=trailing_rounds)
    base_rounds = {
        tuple(row["round"]): row for row in baseline_report.get("rounds") or []
    }
    rounds = []
    wins_both = 0
    for row in candidate_report.get("rounds") or []:
        base = base_rounds.get(tuple(row["round"]))
        if not base:
            continue
        deltas = {}
        wins = []
        for metric in ("log_loss", "rps", "brier"):
            cv = row["metrics"].get(metric)
            bv = base["metrics"].get(metric)
            delta = (cv - bv) if isinstance(cv, (int, float)) and isinstance(bv, (int, float)) else None
            deltas[metric] = round(delta, 5) if isinstance(delta, float) else delta
            if metric in {"log_loss", "rps"} and delta is not None:
                wins.append(delta < 0)
        win_both = len(wins) == 2 and all(wins)
        wins_both += int(win_both)
        rounds.append({
            "round": row["round"],
            "label": row["label"],
            "n": row["n"],
            "candidate": row["metrics"],
            "baseline": base["metrics"],
            "delta_candidate_minus_baseline": deltas,
            "wins_log_loss_and_rps": win_both,
        })

    n_rounds = len(rounds)
    candidate_cum = candidate_report.get("cumulative") or {"n": 0}
    baseline_cum = baseline_report.get("cumulative") or {"n": 0}
    candidate_recent = candidate_report.get("recent") or {"n": 0}
    baseline_recent = baseline_report.get("recent") or {"n": 0}

    def beats(left: dict, right: dict) -> bool:
        return all(
            isinstance(left.get(metric), (int, float))
            and isinstance(right.get(metric), (int, float))
            and left[metric] < right[metric]
            for metric in ("log_loss", "rps")
        )

    cumulative_win = beats(candidate_cum, baseline_cum)
    recent_win = beats(candidate_recent, baseline_recent)
    if cumulative_win and recent_win:
        status = "candidate_ahead_and_stable"
    elif cumulative_win:
        status = "candidate_ahead_but_recently_weaker"
    else:
        status = "baseline_ahead"

    return {
        "method": "paired-rolling-origin-v1",
        "n_predictions": len(candidate),
        "n_rounds": n_rounds,
        "coverage": {
            "candidate": len(candidate_records),
            "baseline": len(baseline_records),
            "paired": len(candidate),
            "same_sample_only": True,
        },
        "rounds": rounds,
        "rounds_won_both": wins_both,
        "round_win_rate_both": round(wins_both / n_rounds, 4) if n_rounds else None,
        "cumulative": {"candidate": candidate_cum, "baseline": baseline_cum},
        "recent": {
            "window_rounds": min(trailing_rounds, n_rounds),
            "candidate": candidate_recent,
            "baseline": baseline_recent,
        },
        "status": status,
        "promotion_gate": False,
    }
