"""Ensemble y calibración temporal para probabilidades 1X2.

Los parámetros se aprenden exclusivamente sobre predicciones walk-forward:
ningún resultado usado para ajustar Dixon-Coles/Elo participa en la predicción
de esa misma jornada. Una cola cronológica se reserva además para validar al
candidato antes de recomendarlo para producción.
"""

from __future__ import annotations

import math

from scipy.optimize import minimize_scalar

from .metrics import aggregate

SIGNS = ("1", "X", "2")


def _normalise(values: dict[str, float]) -> dict[str, float]:
    clipped = {key: max(1e-9, float(values.get(key, 0.0))) for key in SIGNS}
    total = sum(clipped.values()) or 1.0
    return {key: clipped[key] / total for key in SIGNS}


def blend_probabilities(
    dixon_coles: dict[str, float],
    elo: dict[str, float],
    dc_weight: float = 0.75,
) -> dict[str, float]:
    """Pool geométrico DC/Elo, más estable que una media aritmética extrema."""

    weight = max(0.0, min(1.0, float(dc_weight)))
    dc = _normalise(dixon_coles)
    er = _normalise(elo)
    pooled = {
        key: math.exp(weight * math.log(dc[key]) + (1.0 - weight) * math.log(er[key]))
        for key in SIGNS
    }
    return _normalise(pooled)


def temperature_scale(probs: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    """Recalibra una distribución 1X2 sin alterar el orden de favoritos."""

    temp = max(0.35, min(3.0, float(temperature)))
    values = _normalise(probs)
    scaled = {key: values[key] ** (1.0 / temp) for key in SIGNS}
    return _normalise(scaled)


def ensemble_probabilities(
    dixon_coles: dict[str, float],
    elo: dict[str, float],
    dc_weight: float = 0.75,
    temperature: float = 1.0,
) -> dict[str, float]:
    return temperature_scale(blend_probabilities(dixon_coles, elo, dc_weight), temperature)


def _record_key(record: dict) -> tuple:
    return (
        tuple(record.get("round") or ()),
        record.get("home"),
        record.get("away"),
        record.get("actual"),
    )


def _paired(dc_records: list[dict], elo_records: list[dict]) -> list[tuple[dict, dict, str]]:
    elo_by_key = {_record_key(record): record for record in elo_records}
    paired = []
    for dc in dc_records:
        elo = elo_by_key.get(_record_key(dc))
        if elo and dc.get("probs") and elo.get("probs") and dc.get("actual"):
            paired.append((dc["probs"], elo["probs"], dc["actual"]))
    return paired


def _mean_log_loss(rows: list[tuple[dict, dict, str]], weight: float, temp: float) -> float:
    if not rows:
        return float("inf")
    total = 0.0
    for dc, elo, actual in rows:
        prob = ensemble_probabilities(dc, elo, weight, temp)[actual]
        total -= math.log(max(1e-12, prob))
    return total / len(rows)


def _fit_params(rows: list[tuple[dict, dict, str]]) -> tuple[float, float]:
    if len(rows) < 20:
        return 0.75, 1.0

    # Alternancia corta y determinista: peso del ensemble y temperatura.
    weight, temp = 0.75, 1.0
    for _ in range(3):
        fit_w = minimize_scalar(
            lambda value: _mean_log_loss(rows, value, temp),
            bounds=(0.05, 0.95),
            method="bounded",
        )
        if fit_w.success:
            weight = float(fit_w.x)
        fit_t = minimize_scalar(
            lambda value: _mean_log_loss(rows, weight, value),
            bounds=(0.65, 1.8),
            method="bounded",
        )
        if fit_t.success:
            temp = float(fit_t.x)
    return weight, temp


def fit_walk_forward_ensemble(
    dc_records: list[dict],
    elo_records: list[dict],
    validation_fraction: float = 0.30,
) -> dict | None:
    """Aprende en el tramo inicial y valida en la cola cronológica.

    También devuelve parámetros reajustados con todas las predicciones OOF para
    que el siguiente feed pueda usarlos. La métrica de aceptación sigue siendo
    únicamente la de la cola no utilizada para aprender los parámetros.
    """

    rows = _paired(dc_records, elo_records)
    if len(rows) < 30:
        return None
    split = max(20, min(len(rows) - 10, round(len(rows) * (1.0 - validation_fraction))))
    train, validation = rows[:split], rows[split:]
    train_weight, train_temp = _fit_params(train)
    validation_predictions = [
        (ensemble_probabilities(dc, elo, train_weight, train_temp), actual)
        for dc, elo, actual in validation
    ]
    validation_dc = [(dc, actual) for dc, _, actual in validation]
    validation_elo = [(elo, actual) for _, elo, actual in validation]
    validation_metrics = aggregate(validation_predictions)
    dc_metrics = aggregate(validation_dc)
    elo_metrics = aggregate(validation_elo)
    accepted = (
        validation_metrics.get("log_loss", float("inf")) <= dc_metrics.get("log_loss", float("inf"))
        and validation_metrics.get("rps", float("inf")) <= dc_metrics.get("rps", float("inf"))
    )
    prod_weight, prod_temp = _fit_params(rows)
    return {
        "method": "walk-forward-geometric-temperature",
        "n_train": len(train),
        "n_validation": len(validation),
        "accepted": accepted,
        "validation": validation_metrics,
        "validation_baselines": {
            "dixon_coles": dc_metrics,
            "elo": elo_metrics,
        },
        "production": {
            "dc_weight": round(prod_weight, 4),
            "elo_weight": round(1.0 - prod_weight, 4),
            "temperature": round(prod_temp, 4),
            "n": len(rows),
        },
    }
