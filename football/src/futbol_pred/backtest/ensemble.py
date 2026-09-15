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
GATE_METRICS = ("log_loss", "rps")


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


def blend3_probabilities(
    dixon_coles: dict[str, float],
    elo: dict[str, float],
    pi: dict[str, float],
    dc_weight: float = 0.6,
    rating_weight: float = 0.5,
) -> dict[str, float]:
    """Mezcla DC + (Elo/pi) anidando dos pools geométricos de 2 vías.

    Primero se combinan los dos sistemas de rating (Elo y pi-ratings) con
    ``rating_weight`` (peso sobre Elo); el resultado se mezcla con Dixon-Coles con
    ``dc_weight``. Reutiliza la máquina de 2 vías, así que es estable y encaja en
    el mismo gate. Es retrocompatible: sin ``pi`` se usa el ensemble de 2 vías.
    """
    ratings = blend_probabilities(elo, pi, rating_weight)
    return blend_probabilities(dixon_coles, ratings, dc_weight)


def ensemble3_probabilities(
    dixon_coles: dict[str, float],
    elo: dict[str, float],
    pi: dict[str, float],
    dc_weight: float = 0.6,
    rating_weight: float = 0.5,
    temperature: float = 1.0,
) -> dict[str, float]:
    return temperature_scale(
        blend3_probabilities(dixon_coles, elo, pi, dc_weight, rating_weight), temperature
    )


def _record_key(record: dict) -> tuple:
    return (
        tuple(record.get("round") or ()),
        record.get("home"),
        record.get("away"),
        record.get("actual"),
    )


def _paired_records(dc_records: list[dict], elo_records: list[dict]) -> list[tuple[dict, dict]]:
    elo_by_key = {_record_key(record): record for record in elo_records}
    paired = []
    for dc in dc_records:
        elo = elo_by_key.get(_record_key(dc))
        if elo and dc.get("probs") and elo.get("probs") and dc.get("actual"):
            paired.append((dc, elo))
    # Postponed games can appear out of order in a round-based backtest.
    if paired and all(isinstance(dc.get("kickoff"), (int, float)) for dc, _ in paired):
        paired.sort(key=lambda pair: pair[0]["kickoff"])
    return paired


def _paired(dc_records: list[dict], elo_records: list[dict]) -> list[tuple[dict, dict, str]]:
    return [(dc["probs"], elo["probs"], dc["actual"]) for dc, elo in _paired_records(dc_records, elo_records)]


def _paired3_records(dc_records, elo_records, pi_records) -> list[tuple[dict, dict, dict]]:
    elo_by_key = {_record_key(r): r for r in elo_records}
    pi_by_key = {_record_key(r): r for r in pi_records}
    paired = []
    for dc in dc_records:
        elo = elo_by_key.get(_record_key(dc))
        pi = pi_by_key.get(_record_key(dc))
        if elo and pi and dc.get("probs") and elo.get("probs") and pi.get("probs") and dc.get("actual"):
            paired.append((dc, elo, pi))
    if paired and all(isinstance(dc.get("kickoff"), (int, float)) for dc, _, _ in paired):
        paired.sort(key=lambda trio: trio[0]["kickoff"])
    return paired


def _paired3(dc_records, elo_records, pi_records) -> list[tuple[dict, dict, dict, str]]:
    return [(dc["probs"], elo["probs"], pi["probs"], dc["actual"])
            for dc, elo, pi in _paired3_records(dc_records, elo_records, pi_records)]


def _split3_index(triples, dc_records, elo_records, pi_records, desired, min_train, min_validation):
    def block(record):
        stamp = record.get("kickoff")
        return ("day", int(stamp // 86400)) if isinstance(stamp, (int, float)) else ("round", tuple(record.get("round") or ()))
    paired = _paired3_records(dc_records, elo_records, pi_records)
    return grouped_split_index([block(dc) for dc, _, _ in paired], desired, min_train, min_validation)


def _mean_log_loss3(rows, dc_weight, rating_weight, temp) -> float:
    if not rows:
        return float("inf")
    total = 0.0
    for dc, elo, pi, actual in rows:
        prob = ensemble3_probabilities(dc, elo, pi, dc_weight, rating_weight, temp)[actual]
        total -= math.log(max(1e-12, prob))
    return total / len(rows)


def _fit_params3(rows) -> tuple[float, float, float]:
    if len(rows) < 20:
        return 0.6, 0.5, 1.0
    dc_w, rat_w, temp = 0.6, 0.5, 1.0
    for _ in range(3):
        fit_r = minimize_scalar(lambda v: _mean_log_loss3(rows, dc_w, v, temp), bounds=(0.05, 0.95), method="bounded")
        if fit_r.success:
            rat_w = float(fit_r.x)
        fit_d = minimize_scalar(lambda v: _mean_log_loss3(rows, v, rat_w, temp), bounds=(0.05, 0.95), method="bounded")
        if fit_d.success:
            dc_w = float(fit_d.x)
        fit_t = minimize_scalar(lambda v: _mean_log_loss3(rows, dc_w, rat_w, v), bounds=(0.65, 1.8), method="bounded")
        if fit_t.success:
            temp = float(fit_t.x)
    return dc_w, rat_w, temp


def temporal_split_index(dc_records: list[dict], elo_records: list[dict], desired: int,
                         min_train: int, min_validation: int) -> int | None:
    """Keep simultaneous games on one side of the calibration boundary."""
    paired = _paired_records(dc_records, elo_records)
    def block(record):
        stamp = record.get("kickoff")
        return ("day", int(stamp // 86400)) if isinstance(stamp, (int, float)) else ("round", tuple(record.get("round") or ()))
    return grouped_split_index([block(dc) for dc, _ in paired], desired, min_train, min_validation)


def grouped_split_index(blocks: list, desired: int, min_train: int, min_validation: int) -> int | None:
    """Choose a boundary without sharing a collection day/round across splits."""
    choices = [i for i in range(max(1, min_train), len(blocks) - max(1, min_validation) + 1)
               if blocks[i - 1] != blocks[i]]
    return min(choices, key=lambda i: abs(i - desired)) if choices else None


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


def candidate_beats_all_baselines(candidate: dict, baselines: dict[str, dict]) -> bool:
    """Un challenger solo pasa si mejora estrictamente cada métrica de cada campeón."""

    if not baselines:
        return False
    for metric in GATE_METRICS:
        value = candidate.get(metric)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return False
        for baseline in baselines.values():
            reference = baseline.get(metric)
            if (
                not isinstance(reference, (int, float))
                or not math.isfinite(reference)
                or value >= reference
            ):
                return False
    return True


def fit_walk_forward_ensemble(
    dc_records: list[dict],
    elo_records: list[dict],
    validation_fraction: float = 0.30,
    pi_records: list[dict] | None = None,
) -> dict | None:
    """Aprende en el tramo inicial y valida en la cola cronológica.

    También devuelve parámetros reajustados con todas las predicciones OOF para
    que el siguiente feed pueda usarlos. La métrica de aceptación sigue siendo
    únicamente la de la cola no utilizada para aprender los parámetros.

    Si se pasan ``pi_records`` se ajusta el ensemble de 3 vías (DC + Elo +
    pi-ratings) y solo se acepta si bate a los TRES por separado; en su defecto,
    el comportamiento es idéntico al ensemble clásico de 2 vías.
    """

    if pi_records:
        three = _fit_ensemble3(dc_records, elo_records, pi_records, validation_fraction)
        if three is not None:
            return three

    rows = _paired(dc_records, elo_records)
    if len(rows) < 30:
        return None
    split = max(20, min(len(rows) - 10, round(len(rows) * (1.0 - validation_fraction))))
    split = temporal_split_index(dc_records, elo_records, split, 20, 10)
    if split is None:
        return None
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
    baselines = {"dixon_coles": dc_metrics, "elo": elo_metrics}
    accepted = candidate_beats_all_baselines(validation_metrics, baselines)
    prod_weight, prod_temp = _fit_params(rows)
    return {
        "method": "walk-forward-geometric-temperature",
        "n_train": len(train),
        "n_validation": len(validation),
        "accepted": accepted,
        "validation": validation_metrics,
        "validation_baselines": baselines,
        "acceptance_gate": {
            "rule": "strictly_better_than_every_baseline",
            "metrics": list(GATE_METRICS),
            "baselines": list(baselines),
        },
        "production": {
            "dc_weight": round(prod_weight, 4),
            "elo_weight": round(1.0 - prod_weight, 4),
            "temperature": round(prod_temp, 4),
            "n": len(rows),
        },
    }


def _fit_ensemble3(dc_records, elo_records, pi_records, validation_fraction: float = 0.30) -> dict | None:
    """Ensemble de 3 vías DC + Elo + pi-ratings, mismo protocolo de validación."""
    rows = _paired3(dc_records, elo_records, pi_records)
    if len(rows) < 30:
        return None
    split = max(20, min(len(rows) - 10, round(len(rows) * (1.0 - validation_fraction))))
    split = _split3_index(rows, dc_records, elo_records, pi_records, split, 20, 10)
    if split is None:
        return None
    train, validation = rows[:split], rows[split:]
    dc_w, rat_w, temp = _fit_params3(train)
    validation_predictions = [
        (ensemble3_probabilities(dc, elo, pi, dc_w, rat_w, temp), actual)
        for dc, elo, pi, actual in validation
    ]
    baselines = {
        "dixon_coles": aggregate([(dc, actual) for dc, _, _, actual in validation]),
        "elo": aggregate([(elo, actual) for _, elo, _, actual in validation]),
        "pi_ratings": aggregate([(pi, actual) for _, _, pi, actual in validation]),
    }
    validation_metrics = aggregate(validation_predictions)
    accepted = candidate_beats_all_baselines(validation_metrics, baselines)
    prod_dc, prod_rat, prod_temp = _fit_params3(rows)
    return {
        "method": "walk-forward-geometric-temperature-3way",
        "n_train": len(train),
        "n_validation": len(validation),
        "accepted": accepted,
        "validation": validation_metrics,
        "validation_baselines": baselines,
        "acceptance_gate": {
            "rule": "strictly_better_than_every_baseline",
            "metrics": list(GATE_METRICS),
            "baselines": list(baselines),
        },
        "production": {
            "dc_weight": round(prod_dc, 4),
            "rating_weight": round(prod_rat, 4),
            "elo_weight": round(prod_rat, 4),
            "pi_weight": round(1.0 - prod_rat, 4),
            "temperature": round(prod_temp, 4),
            "n": len(rows),
            "components": ["dixon_coles", "elo", "pi_ratings"],
        },
    }
