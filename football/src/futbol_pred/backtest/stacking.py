"""Meta-modelo de stacking log-lineal sobre TODOS los predictores base.

Es la forma responsable (sin dependencias pesadas) del meta-modelo que la
literatura señala como estado del arte: en vez de un pool geométrico de pesos
fijos, aprende un peso por modelo (DC, Elo, pi-ratings, híbrido) minimizando el
log-loss, es decir un *log-linear opinion pool*:

    p_stack(c) ∝ Π_m p_m(c) ** w_m

Un GBM no lineal con features crudas (forma, descanso, mercado) sería el techo,
pero requiere dependencia pesada y validación multi-temporada; aquí el stacker
lineal captura la mayor parte de la ganancia sin dependencias. Se MIDE en el
walk-forward y solo tendría sentido promocionarlo si bate a cada modelo base.
"""

from __future__ import annotations

import math

from scipy.optimize import minimize

from .ensemble import _record_key, candidate_beats_all_baselines, grouped_split_index
from .metrics import aggregate

SIGNS = ("1", "X", "2")


def _pair_models(records_by_model: dict[str, list[dict]]) -> list[dict]:
    """Empareja por partido las probabilidades de todos los modelos + el real.

    Devuelve filas {"probs": {model: {1,X,2}}, "actual", "kickoff", "round"}.
    """
    names = list(records_by_model)
    if len(names) < 2:
        return []
    base = records_by_model[names[0]]
    others = {n: {_record_key(r): r for r in records_by_model[n]} for n in names[1:]}
    rows = []
    for rec in base:
        key = _record_key(rec)
        if not rec.get("probs") or not rec.get("actual"):
            continue
        probs = {names[0]: rec["probs"]}
        ok = True
        for n in names[1:]:
            other = others[n].get(key)
            if not other or not other.get("probs"):
                ok = False
                break
            probs[n] = other["probs"]
        if ok:
            rows.append({"probs": probs, "actual": rec["actual"],
                         "kickoff": rec.get("kickoff"), "round": rec.get("round")})
    if rows and all(isinstance(r.get("kickoff"), (int, float)) for r in rows):
        rows.sort(key=lambda r: r["kickoff"])
    return rows


def _stack_probs(per_model: dict[str, dict], weights: dict[str, float]) -> dict[str, float]:
    logits = {}
    for c in SIGNS:
        s = 0.0
        for name, probs in per_model.items():
            p = min(1.0 - 1e-9, max(1e-9, float(probs.get(c, 0.0))))
            s += weights.get(name, 0.0) * math.log(p)
        logits[c] = s
    m = max(logits.values())
    exp = {c: math.exp(logits[c] - m) for c in SIGNS}
    total = sum(exp.values()) or 1.0
    return {c: exp[c] / total for c in SIGNS}


def _fit_weights(rows: list[dict], names: list[str], l2: float = 1.0) -> dict[str, float]:
    """Pesos por modelo que minimizan log-loss, regularizados hacia 1/K."""
    prior = 1.0 / len(names)

    def nll(w: list[float]) -> float:
        weights = dict(zip(names, w))
        total = 0.0
        for row in rows:
            p = _stack_probs(row["probs"], weights)[row["actual"]]
            total -= math.log(max(1e-12, p))
        penalty = l2 * sum((wi - prior) ** 2 for wi in w)
        return total / len(rows) + penalty

    res = minimize(nll, [prior] * len(names), method="L-BFGS-B",
                   bounds=[(-0.5, 3.0)] * len(names))
    values = res.x if res.success else [prior] * len(names)
    return {n: float(v) for n, v in zip(names, values)}


def fit_walk_forward_stack(
    records_by_model: dict[str, list[dict]],
    validation_fraction: float = 0.30,
) -> dict | None:
    """Aprende los pesos en el tramo inicial y valida en la cola cronológica."""
    rows = _pair_models(records_by_model)
    names = list(records_by_model)
    if len(rows) < 40 or len(names) < 2:
        return None

    def block(row):
        stamp = row.get("kickoff")
        return ("day", int(stamp // 86400)) if isinstance(stamp, (int, float)) else ("round", tuple(row.get("round") or ()))

    desired = max(24, min(len(rows) - 12, round(len(rows) * (1.0 - validation_fraction))))
    split = grouped_split_index([block(r) for r in rows], desired, 24, 12)
    if split is None:
        return None
    train, validation = rows[:split], rows[split:]
    weights = _fit_weights(train, names)
    stacked = [(_stack_probs(r["probs"], weights), r["actual"]) for r in validation]
    validation_metrics = aggregate(stacked)
    baselines = {
        name: aggregate([(r["probs"][name], r["actual"]) for r in validation])
        for name in names
    }
    accepted = candidate_beats_all_baselines(validation_metrics, baselines)
    prod_weights = _fit_weights(rows, names)
    return {
        "method": "walk-forward-log-linear-stack",
        "n_train": len(train),
        "n_validation": len(validation),
        "accepted": accepted,
        "validation": validation_metrics,
        "validation_baselines": baselines,
        "acceptance_gate": {
            "rule": "strictly_better_than_every_baseline",
            "metrics": ["log_loss", "rps"],
            "baselines": names,
        },
        "production": {
            "weights": {n: round(w, 4) for n, w in prod_weights.items()},
            "n": len(rows),
            "components": names,
        },
    }
